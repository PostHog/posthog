import { logger } from '~/common/utils/logger'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag, SessionReplayHeaders } from './pipeline-types'

/**
 * Record-phase per-session step: resolve a session's encryption key, off the S3 write path. Wired under
 * a `groupBy(session)` so it runs once per distinct session and the memory-cached keystore fans the key
 * out to the session's other messages, and under a per-session retry so a transient keystore blip
 * re-runs just that session rather than its batch-siblings.
 *
 * A new session generates a key (using the retention resolved upstream to set the key's expiry); an
 * existing one fetches it. A session whose key has been deleted is dropped. A transient keystore failure
 * (KMS/DynamoDB) throws so the retry wrapper can re-run it; the session is never marked seen before its
 * key exists (see {@link createMarkSeenStep}), so a retry regenerates rather than fetching a key that
 * was never generated — which would record cleartext.
 */
export function createResolveKeyStep<
    T extends {
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    } & NewSessionFlag,
>(keyStore: KeyStore): ProcessingStep<T, T & { sessionKey: SessionKey }> {
    return async function resolveKeyStep(value) {
        const teamId = value.team.teamId
        const sessionId = value.headers.session_id

        const sessionKey = value.isNewSession
            ? await keyStore.generateKey(sessionId, teamId, RetentionPeriodToDaysMap[value.retentionPeriod])
            : await keyStore.getKey(sessionId, teamId)

        if (sessionKey.sessionState === 'deleted') {
            logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                sessionId,
                teamId,
                reason: 'session_deleted',
            })
            return drop('session_deleted')
        }

        return ok({ ...value, sessionKey })
    }
}
