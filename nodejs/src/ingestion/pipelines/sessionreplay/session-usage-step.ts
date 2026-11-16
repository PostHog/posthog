import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import {
    SESSION_TRACKER_MOBILE_BILLED_TTL_SECONDS,
    SESSION_TRACKER_REDIS_TTL_SECONDS,
} from '~/ingestion/pipelines/sessionreplay/constants'
import { BillingClaim, SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { SessionMap } from '~/ingestion/pipelines/sessionreplay/shared/session-map'

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

function billedTtlSeconds(meter: string): number {
    return meter === MOBILE_METER ? SESSION_TRACKER_MOBILE_BILLED_TTL_SECONDS : SESSION_TRACKER_REDIS_TTL_SECONDS
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
 * so a failed send bills on the session's next saved flush. Every send of a session, on any consumer, carries the
 * billing time that the tracker stored first. The usage table then removes each resend.
 */
export async function billPersistedSessions(
    usageBatch: UsageRecordBatch,
    sessionTracker: SessionTracker,
    sessions: SessionBlockMetadata[]
): Promise<void> {
    const claims = new SessionMap<BillingClaim>()
    for (const session of sessions) {
        if (usageBatch.accepts(session.teamId) && !claims.has(session.teamId, session.sessionId)) {
            claims.set(session.teamId, session.sessionId, {
                teamId: session.teamId,
                sessionId: session.sessionId,
                timestampMs: session.captureTimestampMs ?? Date.now(),
                ttlSeconds: billedTtlSeconds(billableMeter(session.snapshotSource)),
            })
        }
    }
    if (claims.size === 0) {
        return
    }

    const billingTimes = await sessionTracker.claimBillingTimes([...claims.values()])
    recordPersistedSessionUsage(
        usageBatch,
        sessions.flatMap((session) => {
            const timestampMs = billingTimes.get(session.teamId, session.sessionId)
            return timestampMs === undefined ? [] : [{ ...session, captureTimestampMs: timestampMs }]
        })
    )
    const received = await usageBatch.flush()
    await sessionTracker.markBilled(
        received.flatMap((record) => {
            const timestampMs = billingTimes.get(record.teamId, record.recordId)
            const claim = claims.get(record.teamId, record.recordId)
            return timestampMs === undefined || !claim
                ? []
                : [{ teamId: record.teamId, sessionId: record.recordId, timestampMs, ttlSeconds: claim.ttlSeconds }]
        })
    )
}
