import { Message } from 'node-rdkafka'

import { BatchProcessingStep } from '../../../../ingestion/pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { EventHeaders } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { SessionBatchManager } from '../sessions/session-batch-manager'
import { SessionBatchRecorder } from '../sessions/session-batch-recorder'
import { TeamForReplay } from '../teams/types'

type Input = { message: Message; headers: EventHeaders; parsedMessage: ParsedMessageData; team: TeamForReplay }
type Output = {
    message: Message
    headers: EventHeaders
    parsedMessage: ParsedMessageData
    team: TeamForReplay
    batchRecorder: SessionBatchRecorder
}

export function createObtainBatchStep(sessionBatchManager: SessionBatchManager): BatchProcessingStep<Input, Output> {
    return function obtainBatchStep(batch: Input[]): Promise<PipelineResult<Output>[]> {
        // Get the current batch recorder once for all messages
        const batchRecorder = sessionBatchManager.getCurrentBatch()

        // Attach the batch recorder to each message
        const results = batch.map((input) =>
            ok({
                ...input,
                batchRecorder,
            })
        )

        return Promise.resolve(results)
    }
}
