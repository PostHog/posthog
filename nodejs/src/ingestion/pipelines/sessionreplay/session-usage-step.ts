import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { ok } from '~/ingestion/framework/results'

import { NewSessionFlag, Recordable, SessionReplayHeaders } from './pipeline-types'
import { ParsedMessageData } from './kafka/types'
import { TeamForReplay } from './teams/types'

type SessionUsageInput = { team: TeamForReplay; headers: SessionReplayHeaders; parsedMessage: ParsedMessageData } & NewSessionFlag

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ChunkProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(values) {
        for (const value of values) {
            if (value.isNewSession) {
                usageBatch?.add(
                    value.team.teamId,
                    'session_replay_recordings',
                    `replay:${value.headers.session_id}`,
                    {
                        snapshot_source: value.parsedMessage.snapshot_source || 'web',
                        ...(value.parsedMessage.snapshot_library
                            ? { snapshot_library: value.parsedMessage.snapshot_library }
                            : {}),
                    }
                )
            }
        }
        return Promise.resolve(values.map(ok))
    }
}
