import {
    AdminClient,
    HighLevelProducer,
    LibrdKafkaError,
    Message,
    KafkaConsumer as RdKafkaConsumer,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { randomUUID } from 'node:crypto'

import { delay } from '../../utils/utils'
import { KafkaConsumer } from './consumer-v1'

/**
 * Integration tests for the KafkaConsumer (v1) partition-revoke wind-down, against a real
 * broker reachable at KAFKA_HOSTS (default: kafka:9092).
 *
 * These validate the contract the session replay consumer relies on for flush-on-revoke,
 * across a matrix of flush durations (instant through multi-second, all below the 20s
 * CONSUMER_REBALANCE_TIMEOUT_MS coordination ceiling):
 *  - the onPartitionsRevoked hook runs while the revoked partitions are still assigned,
 *    no matter how slow the hook is (the unassign waits for it),
 *  - offsets stored inside the hook are committed as part of giving up the partitions,
 *    and the group re-settles to exactly one owner that resumes after them
 *    (no reprocessing, no loss),
 *  - a hook that throws still releases the partitions (the group is never stranded),
 *    leaving offsets uncommitted so the new owner reprocesses (at-least-once),
 *  - a hook outliving the broker-enforced rebalance timeout (max.poll.interval.ms) gets its
 *    member fenced: the rebalance completes without it, the new owner reprocesses from the
 *    last commit, and the slow consumer recovers once its flush finishes.
 *
 * Producing uses a raw HighLevelProducer so every delivery report's assigned offset is kept:
 * all expectations (commit target, per-message content at each exact offset) are derived from
 * what the broker actually assigned rather than assumed.
 *
 * The consumers use the replay-style config (autoCommit on, autoOffsetStore off): offsets
 * reach the broker only if the revoke hook explicitly stores them, which is what makes the
 * committed-offset assertions discriminating.
 */

jest.setTimeout(30_000)

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'kafka:9092'
const KAFKA_CONFIG = { 'metadata.broker.list': KAFKA_HOSTS }

type LedgerEntry = {
    consumerId: string
    partition: number
    offset: number
    key: string
    value: string
    seenAt: number
}

type ProducedRecord = {
    key: string
    value: string
    offset: number
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

async function createRawProducer(): Promise<HighLevelProducer> {
    const producer = new HighLevelProducer(KAFKA_CONFIG)
    await new Promise<void>((resolve, reject) => {
        producer.connect(undefined, (err) => (err ? reject(err) : resolve()))
    })
    producer.setPollInterval(50)
    return producer
}

/**
 * Produces one message per key and returns each delivery report's broker-assigned offset,
 * so tests can assert against exact offsets instead of assuming them.
 */
async function produceTracked(producer: HighLevelProducer, topic: string, keys: string[]): Promise<ProducedRecord[]> {
    return await Promise.all(
        keys.map(
            (key) =>
                new Promise<ProducedRecord>((resolve, reject) => {
                    const value = `payload-${key}`
                    producer.produce(
                        topic,
                        null,
                        Buffer.from(value),
                        Buffer.from(key),
                        Date.now(),
                        [],
                        (err: unknown, offset: number | null | undefined) => {
                            if (err || typeof offset !== 'number') {
                                reject(err ?? new Error('no offset in delivery report'))
                            } else {
                                resolve({ key, value, offset })
                            }
                        }
                    )
                })
        )
    )
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

async function waitForAsync(predicate: () => Promise<boolean>, timeoutMs: number, pollMs = 200): Promise<void> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
        if (await predicate()) {
            return
        }
        await delay(pollMs)
    }
    throw new Error(`waitForAsync timed out after ${timeoutMs}ms`)
}

/**
 * Reads the group's committed offset for a partition via a raw consumer in the same group.
 * Connecting without subscribing does not join the group, so this never triggers a rebalance.
 * Returns null when nothing has been committed yet.
 */
async function fetchCommittedOffset(groupId: string, topic: string, partition: number): Promise<number | null> {
    const consumer = new RdKafkaConsumer({ 'group.id': groupId, ...KAFKA_CONFIG }, {})
    await new Promise<void>((resolve, reject) => {
        consumer.on('ready', () => resolve())
        consumer.on('event.error', (err) => reject(err))
        consumer.connect()
    })
    try {
        const committed = await new Promise<TopicPartitionOffset[]>((resolve, reject) => {
            consumer.committed([{ topic, partition }], 10_000, (err, toppars) =>
                err ? reject(err) : resolve(toppars as TopicPartitionOffset[])
            )
        })
        const offset = committed[0]?.offset
        return typeof offset === 'number' && offset >= 0 ? offset : null
    } finally {
        consumer.disconnect()
    }
}

function makeConsumer(
    groupId: string,
    topic: string,
    eachBatch: (messages: Message[]) => Promise<void>,
    onPartitionsRevoked?: (assignments: { topic: string; partition: number }[]) => Promise<void>,
    rdKafkaOverrides: Record<string, string | number | boolean> = {}
): KafkaConsumer {
    const consumer = new KafkaConsumer(
        {
            groupId,
            topic,
            batchTimeoutMs: 50,
            autoCommit: true,
            autoOffsetStore: false,
            waitForBackgroundTasksOnRebalance: true,
        },
        {
            ...KAFKA_CONFIG,
            'session.timeout.ms': 10_000,
            ...rdKafkaOverrides,
        }
    )
    void consumer.connect(eachBatch, onPartitionsRevoked).catch((err: unknown) => {
        throw new Error(`Consumer failed to connect: ${String(err)}`)
    })
    return consumer
}

describe('KafkaConsumer v1 revoke wind-down (integration)', () => {
    let producer: HighLevelProducer

    beforeAll(async () => {
        producer = await createRawProducer()
    })

    afterAll(async () => {
        await new Promise<void>((resolve) => producer.disconnect(() => resolve()))
    })

    // The revoke contract must hold regardless of how long the flush takes: instant,
    // sub-second, and multi-second (all below the 20s coordination timeout that would
    // force-resume the consume loop).
    it.each([[0], [250], [1000], [3000]])(
        'flush taking %dms: revoke hook runs while assigned, offsets commit on unassign, group re-settles, no reprocessing',
        async (flushDurationMs) => {
            const topic = `v1_int_revoke_commit_${randomUUID()}`
            const groupId = `v1-int-revoke-commit-${randomUUID()}`
            await createTopic(topic, 1)

            const ledger: LedgerEntry[] = []
            let trackedHighestOffset = -1
            // Observations from the first hook invocation (later ones, e.g. at disconnect, are ignored).
            const hook: {
                invocations: number
                revokedPartitions: { topic: string; partition: number }[]
                assignedOnEntry: number
                assignedAfterDelay: number
                storeError: unknown
                completedAt: number
            } = {
                invocations: 0,
                revokedPartitions: [],
                assignedOnEntry: -1,
                assignedAfterDelay: -1,
                storeError: null,
                completedAt: 0,
            }

            const record = (consumerId: string) => (messages: Message[]) => {
                for (const m of messages) {
                    ledger.push({
                        consumerId,
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                    trackedHighestOffset = Math.max(trackedHighestOffset, m.offset)
                }
                return Promise.resolve()
            }

            const consumerA = makeConsumer(groupId, topic, record('A'), async (revoked) => {
                const invocation = ++hook.invocations
                if (invocation > 1) {
                    return
                }
                hook.revokedPartitions = revoked.map((tp) => ({ topic: tp.topic, partition: tp.partition }))
                hook.assignedOnEntry = consumerA.assignments().length
                // The simulated flush: widens the revoke window so an unassign racing ahead
                // of the hook (the regression this test exists for) reliably manifests —
                // either as an empty assignment below or as a store error.
                await delay(flushDurationMs)
                hook.assignedAfterDelay = consumerA.assignments().length
                try {
                    consumerA.offsetsStore([{ topic, partition: 0, offset: trackedHighestOffset + 1 }])
                } catch (e) {
                    hook.storeError = e
                }
                hook.completedAt = Date.now()
            })
            let consumerB: KafkaConsumer | undefined

            try {
                await waitFor(() => consumerA.assignments().length > 0, 10_000)

                const firstWave = await produceTracked(
                    producer,
                    topic,
                    Array.from({ length: 10 }, (_, i) => `k${i}`)
                )
                // Fresh single-partition topic: the broker must have assigned offsets 0..9.
                expect(firstWave.map((r) => r.offset).sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

                await waitFor(() => ledger.length >= firstWave.length, 8_000)

                // Precondition: autoOffsetStore is off and nothing was stored, so nothing is committed.
                // Without this the commit assertion below could pass via the auto-commit timer.
                expect(await fetchCommittedOffset(groupId, topic, 0)).toBeNull()

                // A second member joining forces an eager rebalance: everything is revoked from A.
                consumerB = makeConsumer(groupId, topic, record('B'), () => Promise.resolve())

                await waitFor(() => hook.completedAt > 0, 15_000)

                // The hook was invoked for the partition being revoked, and the partitions were
                // still assigned for the whole duration of the (slow) flush.
                expect(hook.revokedPartitions).toEqual([{ topic, partition: 0 }])
                expect(hook.assignedOnEntry).toBeGreaterThan(0)
                expect(hook.assignedAfterDelay).toBeGreaterThan(0)
                expect(hook.storeError).toBeNull()

                // The rebalance actually completes: the group re-settles with exactly one member
                // owning the partition, and A leaves its rebalancing state.
                const b = consumerB
                await waitFor(() => consumerA.assignments().length + b.assignments().length === 1, 15_000)
                await waitFor(() => !consumerA.isRebalancing(), 10_000)

                // The offsets stored during the hook are committed as part of the unassign, with
                // the exact commit semantics (highest delivered offset + 1) derived from the
                // delivery reports rather than assumed.
                const expectedCommit = Math.max(...firstWave.map((r) => r.offset)) + 1
                await waitForAsync(
                    async () => (await fetchCommittedOffset(groupId, topic, 0)) === expectedCommit,
                    15_000
                )

                // The settled owner resumes after the committed offset: the second wave is
                // consumed, and none of the first wave is ever delivered again.
                const secondWave = await produceTracked(
                    producer,
                    topic,
                    Array.from({ length: 5 }, (_, i) => `k${10 + i}`)
                )
                expect(Math.min(...secondWave.map((r) => r.offset))).toBe(expectedCommit)

                const produced = [...firstWave, ...secondWave]
                await waitFor(() => new Set(ledger.map((e) => e.offset)).size >= produced.length, 15_000)

                // Exact per-message validation: every produced record was consumed at exactly the
                // offset its delivery report announced, with its exact key and value, exactly once.
                expect(ledger.length).toBe(produced.length)
                const consumedByOffset = new Map(ledger.map((e) => [e.offset, { key: e.key, value: e.value }]))
                const producedByOffset = new Map(produced.map((r) => [r.offset, { key: r.key, value: r.value }]))
                expect(consumedByOffset).toEqual(producedByOffset)
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        }
    )

    it('a throwing revoke hook still releases the partitions: the group rebalances and the new owner reprocesses', async () => {
        const topic = `v1_int_revoke_throw_${randomUUID()}`
        const groupId = `v1-int-revoke-throw-${randomUUID()}`
        await createTopic(topic, 1)

        const ledger: LedgerEntry[] = []
        const record = (consumerId: string) => (messages: Message[]) => {
            for (const m of messages) {
                ledger.push({
                    consumerId,
                    partition: m.partition,
                    offset: m.offset,
                    key: m.key?.toString() ?? '',
                    value: m.value?.toString() ?? '',
                    seenAt: Date.now(),
                })
            }
            return Promise.resolve()
        }

        const consumerA = makeConsumer(groupId, topic, record('A'), () => {
            throw new Error('flush failed during revoke')
        })
        let consumerB: KafkaConsumer | undefined

        try {
            await waitFor(() => consumerA.assignments().length > 0, 10_000)
            const firstWave = await produceTracked(
                producer,
                topic,
                Array.from({ length: 10 }, (_, i) => `k${i}`)
            )
            const highestProduced = Math.max(...firstWave.map((r) => r.offset))
            await waitFor(() => ledger.filter((e) => e.consumerId === 'A').length >= firstWave.length, 8_000)

            consumerB = makeConsumer(groupId, topic, record('B'), () => Promise.resolve())

            // The hook threw, so no offsets were stored; the partitions must still be given up
            // and the rebalance complete. The new owner (either member) starts from earliest and
            // redelivers the first wave — consumption resuming at all is the proof the group
            // wasn't stranded, redelivery is the expected at-least-once fallout.
            await waitFor(() => ledger.filter((e) => e.offset === highestProduced).length >= 2, 20_000)
            expect(await fetchCommittedOffset(groupId, topic, 0)).toBeNull()
        } finally {
            await consumerA.disconnect()
            await consumerB?.disconnect()
            await deleteTopic(topic)
        }
    })

    it('a flush exceeding the rebalance timeout: the broker completes the rebalance without it, the new owner reprocesses, the slow consumer recovers', async () => {
        const topic = `v1_int_revoke_slow_${randomUUID()}`
        const groupId = `v1-int-revoke-slow-${randomUUID()}`
        await createTopic(topic, 1)

        // max.poll.interval.ms doubles as the group's broker-enforced rebalance timeout:
        // a member that hasn't rejoined within it is kicked and the rebalance completes
        // without it. 15s timeout with a 25s flush guarantees the slow consumer is fenced
        // mid-flush (the flush also outlives the 20s in-process coordination watchdog).
        const rebalanceTimeoutMs = 15_000
        const flushDurationMs = 25_000

        const ledger: LedgerEntry[] = []
        const hook = { invocations: 0, completedAt: 0 }
        const record = (consumerId: string) => (messages: Message[]) => {
            for (const m of messages) {
                ledger.push({
                    consumerId,
                    partition: m.partition,
                    offset: m.offset,
                    key: m.key?.toString() ?? '',
                    value: m.value?.toString() ?? '',
                    seenAt: Date.now(),
                })
            }
            return Promise.resolve()
        }

        const consumerA = makeConsumer(
            groupId,
            topic,
            record('A'),
            async () => {
                const invocation = ++hook.invocations
                if (invocation > 1) {
                    return
                }
                await delay(flushDurationMs)
                hook.completedAt = Date.now()
            },
            { 'max.poll.interval.ms': rebalanceTimeoutMs }
        )
        let consumerB: KafkaConsumer | undefined

        try {
            await waitFor(() => consumerA.assignments().length > 0, 10_000)
            const firstWave = await produceTracked(
                producer,
                topic,
                Array.from({ length: 10 }, (_, i) => `k${i}`)
            )
            const highestProduced = Math.max(...firstWave.map((r) => r.offset))
            await waitFor(() => ledger.filter((e) => e.consumerId === 'A').length >= firstWave.length, 8_000)

            consumerB = makeConsumer(groupId, topic, record('B'), () => Promise.resolve(), {
                'max.poll.interval.ms': rebalanceTimeoutMs,
            })

            // The broker must complete the rebalance without waiting for the slow flush:
            // B is assigned the partition and (with nothing committed) redelivers the first
            // wave while A's flush is still in progress. This is the guarantee that a slow
            // flush can delay the rebalance only up to the rebalance timeout, never hold the
            // group hostage indefinitely.
            await waitFor(
                () => ledger.filter((e) => e.consumerId === 'B' && e.offset === highestProduced).length >= 1,
                rebalanceTimeoutMs + 10_000
            )
            expect(hook.completedAt).toBe(0)

            // The fenced consumer's flush offsets never made it to the broker: the new owner
            // started from earliest (at-least-once), not from the in-flight flush position.
            expect(await fetchCommittedOffset(groupId, topic, 0)).toBeNull()

            // The slow consumer must recover rather than wedge: once the flush finally
            // finishes, the group settles and newly produced messages are still consumed.
            await waitFor(() => hook.completedAt > 0, flushDurationMs + 10_000)
            const secondWave = await produceTracked(
                producer,
                topic,
                Array.from({ length: 5 }, (_, i) => `k${10 + i}`)
            )
            const secondWaveValues = new Set(secondWave.map((r) => r.value))
            await waitFor(
                () =>
                    secondWaveValues.size ===
                    new Set(ledger.filter((e) => secondWaveValues.has(e.value)).map((e) => e.value)).size,
                20_000
            )
        } finally {
            await consumerA.disconnect()
            await consumerB?.disconnect()
            await deleteTopic(topic)
        }
    }, 90_000)
})
