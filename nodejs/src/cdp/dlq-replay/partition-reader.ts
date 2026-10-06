import { KafkaConsumer, Message } from 'node-rdkafka'
import { hostname } from 'os'

import { getKafkaConfigFromEnv, stripClassicProtocolConfig } from '~/common/kafka/config'

export const REPLAY_GROUP_ID = 'cdp-dlq-replay'

const MAX_EMPTY_READS = 30
const READ_TIMEOUT_MS = 1000

/**
 * Reads one partition of a topic, and commits how far a replay got.
 *
 * Partitions are assigned rather than subscribed, so the workflow decides what runs and the group
 * never rebalances. The committed offsets are the only record of what was replayed, and the next
 * replay starts from them.
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
                'group.id': REPLAY_GROUP_ID,
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
        return (await this.watermarks(topic, partition)).highOffset
    }

    /**
     * The committed offset, or the oldest record still on the topic when nothing was committed yet
     * or retention already deleted past the commit.
     */
    async startOffset(topic: string, partition: number): Promise<number> {
        const [committed] = await new Promise<{ offset?: number }[]>((resolve, reject) =>
            this.consumer.committed([{ topic, partition }], 10_000, (error, data) =>
                error ? reject(error) : resolve(data)
            )
        )
        const { lowOffset } = await this.watermarks(topic, partition)
        return Math.max(committed?.offset ?? -1, lowOffset)
    }

    /** Marks every record before `nextOffset` as replayed. */
    commit(topic: string, partition: number, nextOffset: number): void {
        this.consumer.commitSync({ topic, partition, offset: nextOffset })
    }

    seek(topic: string, partition: number, offset: number): void {
        this.consumer.assign([{ topic, partition, offset }])
    }

    /** An empty read is normal while a fetch is in flight. One that stays empty means the broker is not serving. */
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

    private async watermarks(topic: string, partition: number): Promise<{ lowOffset: number; highOffset: number }> {
        return await new Promise((resolve, reject) =>
            this.consumer.queryWatermarkOffsets(topic, partition, 10_000, (error, data) =>
                error ? reject(error) : resolve(data)
            )
        )
    }
}
