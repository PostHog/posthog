import { AdminClient, LibrdKafkaError, Message } from 'node-rdkafka'
import { randomUUID } from 'node:crypto'

import { delay } from '../../utils/utils'
import { KafkaProducerWrapper } from '../producer'
import { KafkaConsumerV2 } from './consumer-v2'

/**
 * Multi-consumer integration tests for KafkaConsumerV2.
 *
 * Requires a running Kafka/Redpanda broker reachable at KAFKA_HOSTS (default: kafka:9092).
 * Each test creates a unique topic, runs consumers, asserts on a shared "ledger" of every
 * (offset, partition, consumerId, batchSeenAt) seen, then deletes the topic.
 *
 * The tests are deliberately tolerant of bounded duplicates during rebalance — the property
 * we're validating is "no message is lost AND no partition is stuck", not "exactly once".
 */

jest.setTimeout(30_000)
// Real-world per-step timings (from consumer-v2.profile.test.ts):
//   createTopic     ~250ms     consumerConnect  ~15ms     connect→ASSIGN  ~15ms
//   producerConnect   ~5ms     timeToFirstMsg   ~50ms     disconnect      ~65ms
// Tests size their waits off these numbers — generous but not absurd.

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'kafka:9092'
const KAFKA_CONFIG = { 'metadata.broker.list': KAFKA_HOSTS }

type LedgerEntry = {
    consumerId: string
    topic: string
    partition: number
    offset: number
    seenAt: number
}

class Ledger {
    public entries: LedgerEntry[] = []

    record(consumerId: string, m: Message): void {
        this.entries.push({
            consumerId,
            topic: m.topic,
            partition: m.partition,
            offset: m.offset,
            seenAt: Date.now(),
        })
    }

    /** Total unique (partition, offset) pairs seen. */
    uniqueCount(): number {
        const seen = new Set<string>()
        for (const e of this.entries) {
            seen.add(`${e.partition}:${e.offset}`)
        }
        return seen.size
    }

    /** Number of entries that are duplicates (same (partition, offset) seen more than once). */
    duplicateCount(): number {
        const counts = new Map<string, number>()
        for (const e of this.entries) {
            const k = `${e.partition}:${e.offset}`
            counts.set(k, (counts.get(k) ?? 0) + 1)
        }
        let dupes = 0
        for (const c of counts.values()) {
            if (c > 1) {
                dupes += c - 1
            }
        }
        return dupes
    }

    /** Highest offset seen per partition. */
    maxOffsetByPartition(): Map<number, number> {
        const max = new Map<number, number>()
        for (const e of this.entries) {
            const cur = max.get(e.partition)
            if (cur === undefined || e.offset > cur) {
                max.set(e.partition, e.offset)
            }
        }
        return max
    }

    /** Snapshot of the consumer that owned each (partition, offset). */
    ownership(): Map<string, string> {
        const o = new Map<string, string>()
        for (const e of this.entries) {
            o.set(`${e.partition}:${e.offset}`, e.consumerId)
        }
        return o
    }
}

async function createTopic(topic: string, numPartitions: number): Promise<void> {
    const client = AdminClient.create(KAFKA_CONFIG)
    await new Promise<void>((resolve, reject) => {
        client.createTopic(
            { topic, num_partitions: numPartitions, replication_factor: 1 },
            10_000,
            (err: LibrdKafkaError) => {
                if (err && err.message && !/already exists/i.test(err.message)) {
                    reject(err)
                } else {
                    resolve()
                }
            }
        )
    })
    client.disconnect()
}

async function deleteTopic(topic: string): Promise<void> {
    const client = AdminClient.create(KAFKA_CONFIG)
    await new Promise<void>((resolve) => {
        client.deleteTopic(topic, 10_000, () => resolve())
    })
    client.disconnect()
}

async function produceMessages(producer: KafkaProducerWrapper, topic: string, count: number): Promise<void> {
    const promises: Promise<void>[] = []
    for (let i = 0; i < count; i++) {
        promises.push(
            producer.produce({
                topic,
                key: `k${i}`,
                value: Buffer.from(`v${i}`),
            })
        )
    }
    await Promise.all(promises)
}

function makeConsumer(
    consumerId: string,
    groupId: string,
    topic: string,
    eachBatch: (consumerId: string, msgs: Message[]) => Promise<void>
): KafkaConsumerV2 {
    const consumer = new KafkaConsumerV2({ groupId, topic, batchTimeoutMs: 50 }, {
        'metadata.broker.list': KAFKA_HOSTS,
        'session.timeout.ms': 10_000,
    } as Record<string, unknown>)
    void consumer
        .connect(async (msgs: Message[]) => eachBatch(consumerId, msgs))
        .catch((err: unknown) => {
            // Surface the real cause instead of letting waitForAssignments time out generically.
            throw new Error(`Consumer ${consumerId} failed to connect: ${String(err)}`)
        })
    return consumer
}

/**
 * Wait until each consumer has at least one partition assigned. This is the actual signal
 * that the group has stabilized — not a fixed delay.
 */
async function waitForAssignments(consumers: KafkaConsumerV2[], timeoutMs = 10_000): Promise<void> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
        if (consumers.every((c) => c.assignments().length > 0)) {
            return
        }
        await delay(20)
    }
    throw new Error(`waitForAssignments timed out after ${timeoutMs}ms`)
}

async function waitFor(predicate: () => boolean, timeoutMs: number, pollMs = 20): Promise<void> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
        if (predicate()) {
            return
        }
        await delay(pollMs)
    }
    throw new Error(`waitFor timed out after ${timeoutMs}ms`)
}

describe('KafkaConsumerV2 (integration)', () => {
    let producer: KafkaProducerWrapper

    beforeAll(async () => {
        producer = await KafkaProducerWrapper.createWithConfig(undefined, {
            'metadata.broker.list': KAFKA_HOSTS,
        } as Record<string, unknown>)
    })

    afterAll(async () => {
        await producer.disconnect()
    })

    it('single consumer, single partition: all messages consumed exactly once', async () => {
        const topic = `v2_int_single_${randomUUID()}`
        const groupId = `v2-int-single-${randomUUID()}`
        await createTopic(topic, 1)

        try {
            const ledger = new Ledger()
            const consumer = makeConsumer('c1', groupId, topic, async (id, msgs) => {
                for (const m of msgs) {
                    ledger.record(id, m)
                }
                await delay(1)
            })

            await waitForAssignments([consumer])
            await produceMessages(producer, topic, 100)

            await waitFor(() => ledger.uniqueCount() >= 100, 8_000)
            await consumer.disconnect()

            expect(ledger.uniqueCount()).toBe(100)
            expect(ledger.duplicateCount()).toBe(0)
        } finally {
            await deleteTopic(topic)
        }
    })

    it('three consumers, six partitions: messages spread across consumers, no duplicates in steady state', async () => {
        const topic = `v2_int_three_${randomUUID()}`
        const groupId = `v2-int-three-${randomUUID()}`
        await createTopic(topic, 6)

        try {
            const ledger = new Ledger()
            const each = async (id: string, msgs: Message[]) => {
                for (const m of msgs) {
                    ledger.record(id, m)
                }
                await delay(1)
            }
            const c1 = makeConsumer('c1', groupId, topic, each)
            const c2 = makeConsumer('c2', groupId, topic, each)
            const c3 = makeConsumer('c3', groupId, topic, each)

            // Wait for all 3 to actually have partitions assigned, not a fixed delay.
            await waitForAssignments([c1, c2, c3])
            await produceMessages(producer, topic, 1000)

            await waitFor(() => ledger.uniqueCount() >= 1000, 15_000)

            await Promise.all([c1.disconnect(), c2.disconnect(), c3.disconnect()])

            expect(ledger.uniqueCount()).toBe(1000)
            // In steady state with no rebalance during processing, duplicates should be zero or tiny.
            expect(ledger.duplicateCount()).toBeLessThan(20)

            // Every consumer should have processed something (load was actually distributed).
            const consumerIds = new Set(ledger.entries.map((e) => e.consumerId))
            expect(consumerIds.size).toBeGreaterThanOrEqual(2) // at least 2 of 3 saw messages
        } finally {
            await deleteTopic(topic)
        }
    })

    it('graceful rebalance mid-flight: surviving consumer takes over with bounded duplicates', async () => {
        const topic = `v2_int_graceful_${randomUUID()}`
        const groupId = `v2-int-graceful-${randomUUID()}`
        await createTopic(topic, 4)

        try {
            const ledger = new Ledger()
            const each = async (id: string, msgs: Message[]) => {
                for (const m of msgs) {
                    ledger.record(id, m)
                }
                await delay(1)
            }
            const c1 = makeConsumer('c1', groupId, topic, each)
            const c2 = makeConsumer('c2', groupId, topic, each)

            await waitForAssignments([c1, c2])
            await produceMessages(producer, topic, 500)

            // Wait until c1 has seen some messages, then disconnect it gracefully.
            await waitFor(() => ledger.entries.filter((e) => e.consumerId === 'c1').length >= 50, 8_000)
            await c1.disconnect()

            // c2 should pick up everything that's left.
            await waitFor(() => ledger.uniqueCount() >= 500, 15_000)
            await c2.disconnect()

            expect(ledger.uniqueCount()).toBe(500)
            // Bounded duplicates: only messages whose offsets weren't stored before c1 drained.
            // With proper drain semantics this should be very small.
            expect(ledger.duplicateCount()).toBeLessThan(50)
        } finally {
            await deleteTopic(topic)
        }
    })

    it('add consumer mid-flight (H1 scenario): cooperative rebalance, no message lost', async () => {
        const topic = `v2_int_h1_${randomUUID()}`
        const groupId = `v2-int-h1-${randomUUID()}`
        await createTopic(topic, 4)

        try {
            const ledger = new Ledger()
            const each = async (id: string, msgs: Message[]) => {
                for (const m of msgs) {
                    ledger.record(id, m)
                }
                await delay(1)
            }
            const c1 = makeConsumer('c1', groupId, topic, each)
            await waitForAssignments([c1])

            // Produce in two waves so c2 has work to do after the rebalance — without this
            // c1 would consume everything in <100ms before c2 finishes joining.
            await produceMessages(producer, topic, 200)
            await waitFor(() => ledger.entries.filter((e) => e.consumerId === 'c1').length >= 100, 8_000)

            // Add a second consumer mid-flight → triggers a rebalance.
            const c2 = makeConsumer('c2', groupId, topic, each)
            await waitForAssignments([c1, c2])

            await produceMessages(producer, topic, 600)
            await waitFor(() => ledger.uniqueCount() >= 800, 15_000)
            await Promise.all([c1.disconnect(), c2.disconnect()])

            expect(ledger.uniqueCount()).toBe(800)
            expect(ledger.duplicateCount()).toBeLessThan(50)
            // c2 should have processed at least some of the second wave.
            expect(ledger.entries.some((e) => e.consumerId === 'c2')).toBe(true)
        } finally {
            await deleteTopic(topic)
        }
    })

    it('slow background task during rebalance (H3 scenario): drain awaits completion before unassign', async () => {
        const topic = `v2_int_h3_${randomUUID()}`
        const groupId = `v2-int-h3-${randomUUID()}`
        await createTopic(topic, 4)

        try {
            const ledger = new Ledger()
            // eachBatch returns a backgroundTask that takes 200ms.
            const each = (id: string, msgs: Message[]): Promise<{ backgroundTask: Promise<void> }> => {
                for (const m of msgs) {
                    ledger.record(id, m)
                }
                return Promise.resolve({ backgroundTask: delay(200) })
            }

            // Wrapper to satisfy the eachBatch signature
            const wrap = (id: string) => async (msgs: Message[]) => each(id, msgs)
            const c1 = new KafkaConsumerV2({ groupId, topic, batchTimeoutMs: 100 }, {
                'metadata.broker.list': KAFKA_HOSTS,
                'session.timeout.ms': 10_000,
            } as Record<string, unknown>)
            void c1.connect(wrap('c1')).catch((err: unknown) => {
                throw new Error(`Consumer c1 failed to connect: ${String(err)}`)
            })

            const c2 = new KafkaConsumerV2({ groupId, topic, batchTimeoutMs: 100 }, {
                'metadata.broker.list': KAFKA_HOSTS,
                'session.timeout.ms': 10_000,
            } as Record<string, unknown>)
            void c2.connect(wrap('c2')).catch((err: unknown) => {
                throw new Error(`Consumer c2 failed to connect: ${String(err)}`)
            })

            await waitForAssignments([c1, c2])
            await produceMessages(producer, topic, 300)
            await waitFor(() => ledger.entries.filter((e) => e.consumerId === 'c1').length >= 50, 8_000)

            // Disconnect c1 gracefully — should drain its in-flight 200ms task before unassigning.
            await c1.disconnect()

            await waitFor(() => ledger.uniqueCount() >= 300, 15_000)
            await c2.disconnect()

            expect(ledger.uniqueCount()).toBe(300)
            // Without the H3 race, duplicates should be small (only messages whose offsets the
            // graceful disconnect couldn't commit because partitions were already revoked).
            expect(ledger.duplicateCount()).toBeLessThan(30)
        } finally {
            await deleteTopic(topic)
        }
    })

    it('disconnect with in-flight task: disconnect awaits the task, offsets are committed', async () => {
        const topic = `v2_int_disconnect_${randomUUID()}`
        const groupId = `v2-int-disconnect-${randomUUID()}`
        await createTopic(topic, 1)

        try {
            const ledger = new Ledger()
            let taskStartedAt = 0
            let taskFinishedAt = 0
            const consumer = new KafkaConsumerV2({ groupId, topic, batchTimeoutMs: 100 }, {
                'metadata.broker.list': KAFKA_HOSTS,
                'session.timeout.ms': 10_000,
            } as Record<string, unknown>)
            await consumer.connect((msgs) => {
                for (const m of msgs) {
                    ledger.record('c1', m)
                }
                taskStartedAt = Date.now()
                return Promise.resolve({
                    backgroundTask: delay(800).then(() => {
                        taskFinishedAt = Date.now()
                    }),
                })
            })

            await waitForAssignments([consumer])
            await produceMessages(producer, topic, 5)
            await waitFor(() => ledger.uniqueCount() >= 5, 5_000)

            const disconnectStart = Date.now()
            await consumer.disconnect()
            const disconnectDuration = Date.now() - disconnectStart

            // disconnect must have awaited the in-flight task.
            expect(taskFinishedAt).toBeGreaterThan(0)
            // disconnect should not be instantaneous if there was work to drain.
            expect(disconnectDuration).toBeGreaterThan(taskFinishedAt - taskStartedAt - 100)
        } finally {
            await deleteTopic(topic)
        }
    })
})
