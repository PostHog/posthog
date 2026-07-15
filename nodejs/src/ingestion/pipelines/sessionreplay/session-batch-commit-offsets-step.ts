import { OverflowOutput } from '~/common/outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { PipelineResult, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { ReplayRecordRow } from './pipeline-types'

/**
 * Flush step: commit the Kafka offsets the flushed cycle covers, derived from the accumulated
 * per-message rows — every message has a row (recorded, dropped, or DLQ'd), so offsets advance
 * past dropped messages too. In-flight produces (DLQ/overflow) are awaited first, so a message's
 * produce is durable before the offset that covers it is committed. Runs after the write step, so
 * a cycle that fails to persist never commits.
 */
export function createCommitOffsetsStep<T extends { elements: PipelineResult<ReplayRecordRow, OverflowOutput>[] }>(
    offsetManager: KafkaOffsetManager,
    promiseScheduler: PromiseScheduler
): ProcessingStep<T, T> {
    return async function commitOffsetsStep(input) {
        await promiseScheduler.waitForAllSettled()
        for (const element of input.elements) {
            if (isOkResult(element)) {
                offsetManager.trackOffset({ partition: element.value.partition, offset: element.value.offset })
            }
        }
        await offsetManager.commit()
        return ok(input)
    }
}
