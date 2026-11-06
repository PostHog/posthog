import { Message } from 'node-rdkafka'

import { FetchCandidatePoolAdmission, FetchCandidatePoolOwner } from './fetch-candidate-pool'
import { ImageFetchPoolMetrics } from './metrics'

/** consumer-v2 reports a stalled loop after 60 s without a tick, and this wait holds the loop. */
export const POOL_ROOM_WAIT_CAP_MS = 30_000

type BatchProcessor = (messages: Message[], admission: FetchCandidatePoolAdmission) => Promise<void>

/**
 * The batch handler of one consumer in continuous-pool mode.
 *
 * It starts the batch at once and returns only when the consumer's pool window has room, so the
 * consumer reads its next batch while the pool still holds work for it.
 */
export function createPoolWindowBatchHandler(
    owner: FetchCandidatePoolOwner,
    processBatch: BatchProcessor,
    roomWaitCapMs = POOL_ROOM_WAIT_CAP_MS
): (messages: Message[]) => Promise<{ backgroundTask: Promise<void> } | void> {
    return async (messages) => {
        if (messages.length === 0) {
            return
        }
        const admission = owner.beginAdmission()
        const backgroundTask = processBatch(messages, admission).finally(() => admission.admitted())
        // consumer-v2 attaches its own handler after this returns, so a failure during the wait must not count as unhandled.
        void backgroundTask.catch(() => undefined)
        const waitStartedAtMs = performance.now()
        const hadRoom = await owner.waitForRoom(roomWaitCapMs)
        ImageFetchPoolMetrics.observeRefillWait(
            hadRoom ? 'room' : 'timeout',
            (performance.now() - waitStartedAtMs) / 1000
        )
        return { backgroundTask }
    }
}
