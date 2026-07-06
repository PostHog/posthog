import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Gated, NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'

/** The minimal per-element shape this step needs to resolve a session's key. */
type ResolveKeyStepInput = {
    team: TeamForReplay
    headers: SessionReplayHeaders
    retentionPeriod: RetentionPeriod
} & NewSessionFlag

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
 * rate limit every batch.
 *
 * This step is the encryption boundary, so it obeys the integrity rule (rule 2 — see {@link SessionTracker}
 * class doc): it FAILS HARD rather than ever producing a keyless recording. A transient keystore failure
 * (KMS/DynamoDB) throws so the retry wrapper re-runs it. And because the session is never marked seen
 * before its key is durably generated (see {@link createMarkSeenStep}), a retry regenerates the key
 * rather than fetching one that was never created — which would record cleartext. The upstream
 * {@link createTrackAndGateStep} guarantees the new-vs-existing input here is correct or absent (its
 * hasSeen also fails hard), so this step never fetches a key for a genuinely-new session.
 */
export function createResolveKeyStep<T extends ResolveKeyStepInput>(
    keyStore: KeyStore
): ProcessingStep<Gated<T>, Resolved<T>> {
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
