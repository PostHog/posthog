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

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const snapshotSource = value.parsedMessage.snapshot_source || 'web'
            const dimensions = {
                snapshot_source: snapshotSource,
                ...(value.parsedMessage.snapshot_library
                    ? { snapshot_library: value.parsedMessage.snapshot_library }
                    : {}),
            }
            usageBatch?.add(value.team.teamId, 'session_replay_recordings', value.headers.session_id, dimensions)
            if (snapshotSource === 'mobile') {
                usageBatch?.add(value.team.teamId, 'mobile_replay_recordings', value.headers.session_id, dimensions)
            }
        }
        return Promise.resolve(ok(value))
    }
}
