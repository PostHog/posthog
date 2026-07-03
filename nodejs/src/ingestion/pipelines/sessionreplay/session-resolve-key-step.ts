import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Gated, NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'

/**
 * Record-phase per-session step: resolve a session's encryption key, off the S3 write path. Wired under
 * a `groupBy(session)` so it runs once per distinct session and the memory-cached keystore fans the key
 * out to the session's other messages, and under a per-session retry so a transient keystore blip
 * re-runs just that session rather than its batch-siblings.
 *
 * A blocked session rides through untouched (no key resolved). An allowed new session generates a key
 * (using the retention resolved upstream to set the key's expiry); an allowed existing one fetches it.
 * A session whose key has been deleted is re-tagged `deleted` and carried through too — like blocked, the
 * mark-seen step marks it seen and then drops it, so a deleted session isn't re-counted against the
 * rate limit every batch. A transient keystore failure (KMS/DynamoDB) throws so the retry wrapper can
 * re-run it; the session is never marked seen before its key exists (see {@link createMarkSeenStep}), so
 * a retry regenerates rather than fetching a key that was never generated — which would record cleartext.
 */
export function createResolveKeyStep<
    T extends {
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    } & NewSessionFlag,
>(keyStore: KeyStore): ProcessingStep<Gated<T>, Resolved<T>> {
    return async function resolveKeyStep(value) {
        if (value.status === 'blocked') {
            return ok(value)
        }

        const teamId = value.team.teamId
        const sessionId = value.headers.session_id

        const sessionKey = value.isNewSession
            ? await keyStore.generateKey(sessionId, teamId, RetentionPeriodToDaysMap[value.retentionPeriod])
            : await keyStore.getKey(sessionId, teamId)

        if (sessionKey.sessionState === 'deleted') {
            return ok({ ...value, status: 'deleted' as const })
        }

        return ok({ ...value, sessionKey })
    }
}
