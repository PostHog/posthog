import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { ReplayCycleState } from './pipeline-types'

/**
 * Flush step: commit the Kafka offsets the flushed cycle covers, read off the reduced cycle state —
 * every message counted (recorded, dropped, or DLQ'd), so offsets advance past dropped messages
 * too. In-flight produces (DLQ/overflow) are awaited first, so a message's produce is durable
 * before the offset that covers it is committed. Runs after the write step, so a cycle that fails
 * to persist never commits.
 */
export function createCommitOffsetsStep<T extends { state: ReplayCycleState }>(
    offsetManager: KafkaOffsetManager,
    promiseScheduler: PromiseScheduler
): ProcessingStep<T, T> {
    return async function commitOffsetsStep(input) {
        await promiseScheduler.waitForAllSettled()
        for (const [partition, offset] of input.state.offsets) {
            offsetManager.trackOffset({ partition, offset })
        }
        await offsetManager.commit()
        return ok(input)
    }
}
