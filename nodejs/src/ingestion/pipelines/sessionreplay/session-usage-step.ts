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

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const snapshotSource = value.parsedMessage.snapshot_source || 'web'
            if (snapshotSource !== 'mobile') {
                usageBatch?.add(value.team.teamId, 'session_replay_recordings', value.headers.session_id)
            } else if (BILLABLE_MOBILE_LIBRARIES.has(value.parsedMessage.snapshot_library || '')) {
                usageBatch?.add(value.team.teamId, 'mobile_replay_recordings', value.headers.session_id)
            }
        }
        return Promise.resolve(ok(value))
    }
}
