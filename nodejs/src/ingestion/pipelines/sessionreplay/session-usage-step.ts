import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { ParsedMessageData } from './kafka/types'
import { NewSessionFlag, Recordable, SessionReplayHeaders } from './pipeline-types'
import { TeamForReplay } from './teams/types'

type SessionUsageInput = {
    team: TeamForReplay
    headers: SessionReplayHeaders
    parsedMessage: ParsedMessageData
} & NewSessionFlag

// The report bills mobile replay only from the SDKs it lists, and counts a web recording
// and a mobile one under separate meters, so a mobile session is never both.
const BILLABLE_MOBILE_LIBRARIES = new Set(['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'])

/**
 * The meter the report would bill this session under, or null for neither. `snapshot_source` is
 * client-supplied, and the report matches `web` and `mobile` exactly, so an unrecognized value
 * belongs to no meter — reading anything non-mobile as web would bill what the report does not.
 *
 * Both meters read the first message processed for the session. The report instead reads the
 * earliest snapshot's metadata, so the two disagree if one session's messages disagree with each
 * other about their source or library, which no single client does.
 */
function billableMeter(snapshotSource: string | null, snapshotLibrary: string | null): string | null {
    if ((snapshotSource || 'web') === 'web') {
        return 'session_replay_recordings'
    }
    if (snapshotSource === 'mobile' && BILLABLE_MOBILE_LIBRARIES.has(snapshotLibrary || '')) {
        return 'mobile_replay_recordings'
    }
    return null
}

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const meter = billableMeter(value.parsedMessage.snapshot_source, value.parsedMessage.snapshot_library)
            if (meter) {
                usageBatch?.add(value.team.teamId, meter, value.headers.session_id)
            }
        }
        return Promise.resolve(ok(value))
    }
}
