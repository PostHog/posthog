import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { logger } from '~/common/utils/logger'

import { REPLAY_COUNT_HEADER } from './image-batcher'
import { CAPTURE_TIMESTAMP_HEADER, CONTENT_ENCODING_HEADER, CONTENT_TYPE_HEADER } from './image-transport'
import { ImageScrubConsumerMetrics } from './metrics'

/**
 * Replays past which an image stays parked.
 *
 * A replay run is only worth making after the sidecar has been fixed, but nothing enforces that, and
 * an image pushed back at a sidecar that still cannot handle it simply returns to the dead-letter
 * topic. Capping the round trips means running the replay too early costs one wasted pass instead of
 * a loop, so the safe outcome does not depend on an operator getting the order right.
 */
export const MAX_REPLAYS = 2

export interface ReplayOutcome {
    replayed: number
    exhausted: number
}

/**
 * Pushes parked images back onto the topic they came from.
 *
 * The value is passed through untouched, because it is the original image and the point of the
 * exercise is to put it through a fixed sidecar exactly as it arrived the first time. The key is the
 * ref, so it lands on the partition the rest of that image's copies hash to.
 *
 * Diagnostic headers from the park are deliberately dropped because they describe an old failure.
 * The content headers survive because the consumer needs them to decode and validate fetched images.
 * The replay count also survives because it stops an image circling between the two topics.
 */
export async function replayBatch(
    messages: Message[],
    producer: KafkaProducerWrapper,
    sourceTopic: string
): Promise<ReplayOutcome> {
    const outcome: ReplayOutcome = { replayed: 0, exhausted: 0 }
    for (const message of messages) {
        const ref = message.key?.toString('utf8')
        if (!ref || !message.value) {
            continue
        }
        const headers = parseKafkaHeaders(message.headers)
        const replayCount = Number(headers[REPLAY_COUNT_HEADER] ?? 0) || 0
        if (replayCount >= MAX_REPLAYS) {
            // Left where it is rather than dropped: the bytes stay on the dead-letter topic for
            // whatever retention it has, which is the only copy of them that exists.
            outcome.exhausted += 1
            ImageScrubConsumerMetrics.incReplayExhausted()
            logger.warn('☠️', 'image_scrub_replay_exhausted', { ref, replayCount, reason: headers.reason })
            continue
        }
        await producer.produce({
            topic: sourceTopic,
            key: Buffer.from(ref),
            value: message.value,
            headers: {
                ...(headers[CONTENT_TYPE_HEADER] ? { [CONTENT_TYPE_HEADER]: headers[CONTENT_TYPE_HEADER] } : {}),
                ...(headers[CONTENT_ENCODING_HEADER]
                    ? { [CONTENT_ENCODING_HEADER]: headers[CONTENT_ENCODING_HEADER] }
                    : {}),
                ...(headers[CAPTURE_TIMESTAMP_HEADER]
                    ? { [CAPTURE_TIMESTAMP_HEADER]: headers[CAPTURE_TIMESTAMP_HEADER] }
                    : {}),
                [REPLAY_COUNT_HEADER]: String(replayCount + 1),
            },
        })
        outcome.replayed += 1
        ImageScrubConsumerMetrics.incReplayed()
    }
    return outcome
}
