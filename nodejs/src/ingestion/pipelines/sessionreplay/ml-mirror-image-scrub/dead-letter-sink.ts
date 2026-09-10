import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { DeadLetterSink } from './image-batcher'

/**
 * Parks an image the sidecar cannot process onto a Kafka topic, keyed by ref like the source.
 *
 * The value is the original bytes, unchanged. That is the point: the image was never scrubbed, so it
 * still carries whatever it always did and must not reach the ML bucket, but discarding it would
 * destroy the only reproduction of the sidecar bug that rejected it. The topic keeps both properties
 * at once, and the retention on it is the window in which someone can fix the sidecar and replay.
 *
 * Everything about why it was parked goes in headers rather than the value, so a consumer can triage
 * the topic without reading a byte of image content.
 */
export class KafkaDeadLetterSink implements DeadLetterSink {
    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly topic: string
    ) {}

    public async park(image: {
        ref: string
        bytes: Buffer
        headers: Record<string, string>
        detail: Record<string, unknown>
    }): Promise<void> {
        await this.producer.produce({
            topic: this.topic,
            key: Buffer.from(image.ref),
            value: image.bytes,
            headers: {
                ...image.headers,
                ...Object.fromEntries(Object.entries(image.detail).map(([k, v]) => [k, String(v)])),
            },
        })
    }
}
