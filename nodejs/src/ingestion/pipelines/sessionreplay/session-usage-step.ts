import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import {
    SESSION_TRACKER_MOBILE_BILLED_TTL_SECONDS,
    SESSION_TRACKER_REDIS_TTL_SECONDS,
} from '~/ingestion/pipelines/sessionreplay/constants'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'

const MOBILE_METER = 'mobile_replay_recordings'

/**
 * The meter this session bills under. Every session bills exactly one, so no `snapshot_source`
 * buys a free recording.
 *
 * Anything other than `mobile` is a web recording, including a value no SDK sends. Nothing between
 * the SDK and here validates the field, so matching `web` exactly would let any other string bill
 * nowhere. The report does match it exactly, and bills a mobile recording only from four named
 * libraries, so it bills neither meter for a session outside those values. Those are holes on its
 * side rather than a contract to copy.
 *
 * The meter reads the snapshot source stored with the replay metadata.
 */
function billableMeter(snapshotSource: string | null): string {
    return snapshotSource === 'mobile' ? MOBILE_METER : 'session_replay_recordings'
}

export function recordPersistedSessionUsage(usageBatch: UsageRecordBatch, sessions: SessionBlockMetadata[]): void {
    for (const session of sessions) {
        usageBatch.add(
            session.teamId,
            billableMeter(session.snapshotSource),
            session.sessionId,
            1,
            undefined,
            session.captureTimestampMs
        )
    }
}

/**
 * Bills each saved session once. A session counts as billed only after its record reaches the usage service,
 * so a failed send bills on the session's next saved flush.
 */
export async function billPersistedSessions(
    usageBatch: UsageRecordBatch,
    sessionTracker: SessionTracker,
    sessions: SessionBlockMetadata[]
): Promise<void> {
    const billable = new SessionSet()
    for (const session of sessions) {
        if (usageBatch.accepts(session.teamId)) {
            billable.add(session.teamId, session.sessionId)
        }
    }
    if (billable.size === 0) {
        return
    }

    const unbilled = await sessionTracker.findUnbilled(billable)
    recordPersistedSessionUsage(
        usageBatch,
        sessions.filter((session) => unbilled.has(session.teamId, session.sessionId))
    )
    const received = await usageBatch.flush()
    await sessionTracker.markBilled(
        received
            .filter((record) => unbilled.has(record.teamId, record.recordId))
            .map((record) => ({
                teamId: record.teamId,
                sessionId: record.recordId,
                ttlSeconds:
                    record.usageKey === MOBILE_METER
                        ? SESSION_TRACKER_MOBILE_BILLED_TTL_SECONDS
                        : SESSION_TRACKER_REDIS_TTL_SECONDS,
            }))
    )
}
