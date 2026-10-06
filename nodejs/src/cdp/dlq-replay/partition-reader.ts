import { KafkaConsumer, Message } from 'node-rdkafka'
import { hostname } from 'os'

import { getKafkaConfigFromEnv, stripClassicProtocolConfig } from '~/common/kafka/config'

const MAX_EMPTY_READS = 30
const READ_TIMEOUT_MS = 1000

/**
 * Reads one partition of a topic from a given offset, with no consumer group.
 *
 * The replay activity tracks its own position and checkpoints it in its heartbeat, so nothing is
 * committed here. Two runs over the same window read the same records, which is what lets an
 * operator re-run a replay or a retry pick up where the last attempt stopped.
 */
export class DlqPartitionReader {
    private constructor(private consumer: KafkaConsumer) {}

    static async open(): Promise<DlqPartitionReader> {
        const consumer = new KafkaConsumer(
            stripClassicProtocolConfig({
                'client.id': hostname(),
                'security.protocol': 'plaintext',
                'metadata.broker.list': 'kafka:9092',
                ...getKafkaConfigFromEnv('CONSUMER'),
                // librdkafka refuses a consumer without a group. Offsets are never stored or
                // committed under it, so it only names the client in broker logs.
                'group.id': 'cdp-dlq-replay',
                'enable.auto.commit': false,
                'enable.auto.offset.store': false,
                'enable.partition.eof': false,
            }),
            {}
        )
        await new Promise<void>((resolve, reject) =>
            consumer.connect({}, (error) => (error ? reject(error) : resolve()))
        )
        consumer.setDefaultConsumeTimeout(READ_TIMEOUT_MS)
        return new DlqPartitionReader(consumer)
    }

    async partitions(topic: string): Promise<number[]> {
        const metadata = await new Promise<any>((resolve, reject) =>
            this.consumer.getMetadata({ topic, timeout: 10_000 }, (error, data) =>
                error ? reject(error) : resolve(data)
            )
        )
        const found = metadata.topics.find((entry: { name: string }) => entry.name === topic)
        // An unknown topic is an error, not an empty replay: a run that reports zero records
        // because of a typo or the wrong cluster looks exactly like a clean run.
        if (!found || !found.partitions.length) {
            throw new Error(`Topic ${topic} has no partitions on this cluster`)
        }
        return found.partitions.map((partition: { id: number }) => partition.id).sort((a: number, b: number) => a - b)
    }

    async highWatermark(topic: string, partition: number): Promise<number> {
        const offsets = await new Promise<{ highOffset: number }>((resolve, reject) =>
            this.consumer.queryWatermarkOffsets(topic, partition, 10_000, (error, data) =>
                error ? reject(error) : resolve(data)
            )
        )
        return offsets.highOffset
    }

    async offsetForTime(topic: string, partition: number, timestampMs: number): Promise<number> {
        const [found] = await new Promise<{ offset: number }[]>((resolve, reject) =>
            this.consumer.offsetsForTimes([{ topic, partition, offset: timestampMs }], 10_000, (error, data) =>
                error ? reject(error) : resolve(data)
            )
        )
        return found && found.offset >= 0 ? found.offset : await this.highWatermark(topic, partition)
    }

    seek(topic: string, partition: number, offset: number): void {
        this.consumer.assign([{ topic, partition, offset }])
    }

    async read(max: number): Promise<Message[]> {
        for (let attempt = 0; attempt < MAX_EMPTY_READS; attempt++) {
            const messages = await new Promise<Message[]>((resolve, reject) =>
                this.consumer.consume(max, (error, data) => (error ? reject(error) : resolve(data)))
            )
            if (messages.length) {
                return messages
            }
        }
        throw new Error(`No records after ${MAX_EMPTY_READS} reads although the partition has more`)
    }

    async close(): Promise<void> {
        await new Promise<void>((resolve) => this.consumer.disconnect(() => resolve()))
    }
}
