import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { AfterRecordHook } from '~/ingestion/framework/accumulating-pipeline'
import { isOkResult, ok } from '~/ingestion/framework/results'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { SessionReplayPipelineOutput } from './session-replay-pipeline'

/**
 * Trimmed record result: the heavy Kafka `message` and parsed payload are dropped once a message is
 * recorded, so what accumulates for the flush is a lightweight per-message row.
 */
export interface TrimmedReplayElement {
    partition: number
    timestamp: number
}

/**
 * afterRecord hook for the session replay pipeline. For every drained record result (ok, drop, dlq,
 * redirect) it tracks the source message's offset — so dropped and DLQ'd messages advance offsets
 * too — and trims the element so the flush buffer never pins the raw Kafka payloads: OK results
 * become a lightweight row, non-OK results pass through as results. Side effects were already
 * lifted off the contexts by the accumulating pipeline, so the fresh contexts here lose nothing.
 */
export function createReplayAfterRecordHook(
    offsetManager: KafkaOffsetManager
): AfterRecordHook<
    SessionReplayPipelineOutput,
    { message: Message },
    TrimmedReplayElement,
    Record<never, object>,
    OverflowOutput
> {
    return function replayAfterRecord(elements) {
        return elements.map((element) => {
            offsetManager.trackOffset({
                partition: element.context.message.partition,
                offset: element.context.message.offset,
            })
            return {
                result: isOkResult(element.result)
                    ? ok({
                          partition: element.context.message.partition,
                          timestamp: Date.now(),
                      })
                    : element.result,
                context: { sideEffects: [], warnings: [] },
            }
        })
    }
}
