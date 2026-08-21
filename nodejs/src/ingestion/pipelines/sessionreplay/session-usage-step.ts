import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { ok } from '~/ingestion/framework/results'

import { NewSessionFlag, Recordable, Resolved, SessionReplayHeaders } from './pipeline-types'
import { TeamForReplay } from './teams/types'

type SessionUsageInput = { team: TeamForReplay; headers: SessionReplayHeaders } & NewSessionFlag

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ChunkProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(values) {
        for (const value of values) {
            if (value.isNewSession) {
                usageBatch?.add(
                    value.team.teamId,
                    'session_replay_recordings',
                    `replay:${value.headers.session_id}`
                )
            }
        }
        return Promise.resolve(values.map(ok))
    }
}
