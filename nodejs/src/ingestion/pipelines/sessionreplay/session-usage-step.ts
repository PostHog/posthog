import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

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
    return snapshotSource === 'mobile' ? 'mobile_replay_recordings' : 'session_replay_recordings'
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
