import {
    AdminClient,
    HighLevelProducer,
    LibrdKafkaError,
    Message,
    KafkaConsumer as RdKafkaConsumer,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { randomUUID } from 'node:crypto'

import { defaultConfig } from '../../config/config'
import { delay } from '../../utils/utils'
import { KafkaConsumerV2 } from './consumer-v2'

/**
 * Exact rebalance-semantics tests for KafkaConsumerV2, against a real broker reachable at
 * KAFKA_HOSTS (default: kafka:9092). The existing consumer-v2.integration.test.ts validates
 * liveness properties with tolerance ("no loss, bounded duplicates"); this suite pins the
 * exact offset semantics of a cooperative rebalance:
 *  - work settled before the rebalance is committed at exactly the delivered offsets, and
 *    the new owner resumes with zero redelivery,
 *  - cooperative-sticky revokes are incremental: the surviving consumer never drops to zero
 *    assignments while a partition moves,
 *  - the generation guard: a batch in flight when the revoke arrives skips its offset store,
 *    so its messages are redelivered on the moved partition (exactly once more) while the
 *    retained partition never re-reads them and the group commit stays at the pre-batch mark,
 *  - the onPartitionsRevoked hook (the session replay flush-on-revoke contract): it runs
 *    after the drain while the partitions are still assigned, offsets it stores are committed
 *    exactly as the partitions are given up — including from an already-committed baseline
 *    when a flushed cycle precedes the in-flight one — a throwing hook never strands the
 *    rebalance, a hook outliving the consumer's own budget (CONSUMER_REBALANCE_TIMEOUT_MS) is
 *    abandoned — the rebalance proceeds without fencing the member and the late store for the
 *    moved partition is discarded — and a hook outliving the broker-enforced rebalance timeout
 *    (max.poll.interval.ms) gets the member fenced, its late store discarded, and recovers,
 *  - the two-phase shutdown (the session replay flush-on-stop contract): stopConsuming
 *    resolves only after in-flight work drains and halts intake for good, offsets stored
 *    between stopConsuming and disconnect are committed as the member leaves, and a restart
 *    resumes exactly after them.
 *
 * Producing uses a raw HighLevelProducer with explicit partitions so every delivery report's
 * assigned offset is kept; all expectations are derived from those reports, never assumed.
 */

jest.setTimeout(60_000)

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
    partition: number
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
 * Produces one message per (key, partition) pair and returns each delivery report's
 * broker-assigned offset, so tests can assert against exact offsets instead of assuming them.
 */
async function produceTracked(
    producer: HighLevelProducer,
    topic: string,
    records: { key: string; partition: number }[]
): Promise<ProducedRecord[]> {
    return await Promise.all(
        records.map(
            ({ key, partition }) =>
                new Promise<ProducedRecord>((resolve, reject) => {
                    const value = `payload-${key}`
                    producer.produce(
                        topic,
                        partition,
                        Buffer.from(value),
                        Buffer.from(key),
                        Date.now(),
                        [],
                        (err: unknown, offset: number | null | undefined) => {
                            if (err || typeof offset !== 'number') {
                                reject(err ?? new Error('no offset in delivery report'))
                            } else {
                                resolve({ key, value, partition, offset })
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
    eachBatch: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> } | void>,
    opts: {
        autoOffsetStore?: boolean
        onPartitionsRevoked?: (assignments: { topic: string; partition: number }[]) => Promise<void>
        rdKafkaOverrides?: Record<string, string | number | boolean>
    } = {}
): KafkaConsumerV2 {
    const consumer = new KafkaConsumerV2(
        { groupId, topic, batchTimeoutMs: 50, autoOffsetStore: opts.autoOffsetStore },
        {
            ...KAFKA_CONFIG,
            // Short but realistic session timeout keeps group transitions in these tests fast.
            // 6s is the broker's floor (group.min.session.timeout.ms defaults to 6000).
            'session.timeout.ms': 6_000,
            // The broker-enforced rebalance timeout (librdkafka sends max.poll.interval.ms as
            // the JoinGroup rebalance timeout). Every flush in this suite must finish inside
            // it — except in the fencing test, which lowers it deliberately to get fenced.
            'max.poll.interval.ms': 30_000,
            // Commit stored offsets promptly so exact committed-offset assertions don't wait
            // out the 5s librdkafka default between polls.
            'auto.commit.interval.ms': 500,
            ...opts.rdKafkaOverrides,
        } as Record<string, unknown>
    )
    void consumer.connect(eachBatch, opts.onPartitionsRevoked).catch((err: unknown) => {
        throw new Error(`Consumer failed to connect: ${String(err)}`)
    })
    return consumer
}

function countByPartitionOffset(ledger: LedgerEntry[]): Map<string, number> {
    const counts = new Map<string, number>()
    for (const e of ledger) {
        const k = `${e.partition}:${e.offset}`
        counts.set(k, (counts.get(k) ?? 0) + 1)
    }
    return counts
}

describe('KafkaConsumerV2 rebalance semantics (integration)', () => {
    let producer: HighLevelProducer

    beforeAll(async () => {
        producer = await createRawProducer()
    })

    afterAll(async () => {
        await new Promise<void>((resolve) => producer.disconnect(() => resolve()))
    })

    // v2's automatic offset path: each settled batch stores highest+1 itself, and librdkafka
    // commits stored offsets on the auto-commit timer and on unassign. No test code in this
    // group stores offsets.
    describe('autoOffsetStore on: offsets stored automatically as batches settle', () => {
        it('settled work commits exactly; cooperative rebalance moves one partition with zero redelivery', async () => {
            const topic = `v2_int_reb_exact_${randomUUID()}`
            const groupId = `v2-int-reb-exact-${randomUUID()}`
            await createTopic(topic, 2)

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

            const consumerA = makeConsumer(groupId, topic, record('A'), { autoOffsetStore: true })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)

                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 5 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 5 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                // Fresh topic: the broker must have assigned offsets 0..4 on each partition.
                for (const partition of [0, 1]) {
                    expect(
                        wave1
                            .filter((r) => r.partition === partition)
                            .map((r) => r.offset)
                            .sort((x, y) => x - y)
                    ).toEqual([0, 1, 2, 3, 4])
                }
                await waitFor(() => ledger.length >= wave1.length, 8_000)

                // With every batch settled, the stored offsets are committed at exactly
                // highest-delivered + 1 per partition.
                const expectedCommit = new Map<number, number>()
                for (const partition of [0, 1]) {
                    const highest = Math.max(...wave1.filter((r) => r.partition === partition).map((r) => r.offset))
                    expectedCommit.set(partition, highest + 1)
                }
                for (const [partition, offset] of expectedCommit) {
                    await waitForAsync(
                        async () => (await fetchCommittedOffset(groupId, topic, partition)) === offset,
                        10_000
                    )
                }

                // B joins: cooperative-sticky moves exactly one partition, and A never drops to
                // zero assignments while it happens (the incremental-rebalance property).
                consumerB = makeConsumer(groupId, topic, record('B'), { autoOffsetStore: true })
                const b = consumerB
                let minAssignedA = 2
                await waitFor(() => {
                    minAssignedA = Math.min(minAssignedA, consumerA.assignments().length)
                    return consumerA.assignments().length === 1 && b.assignments().length === 1
                }, 15_000)
                expect(minAssignedA).toBeGreaterThanOrEqual(1)

                // The new owner resumes from the exact committed offsets: a second wave lands
                // contiguously after the first, and nothing from the first wave is redelivered.
                const wave2 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${5 + i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${5 + i}`, partition: 1 })),
                ])
                for (const partition of [0, 1]) {
                    expect(Math.min(...wave2.filter((r) => r.partition === partition).map((r) => r.offset))).toBe(
                        expectedCommit.get(partition)
                    )
                }

                const produced = [...wave1, ...wave2]
                await waitFor(() => countByPartitionOffset(ledger).size >= produced.length, 15_000)

                // Exact per-message validation: every produced record consumed at exactly the
                // (partition, offset) its delivery report announced, exactly once, correct content.
                expect(ledger.length).toBe(produced.length)
                const consumedAt = new Map(
                    ledger.map((e) => [`${e.partition}:${e.offset}`, { key: e.key, value: e.value }])
                )
                const producedAt = new Map(
                    produced.map((r) => [`${r.partition}:${r.offset}`, { key: r.key, value: r.value }])
                )
                expect(consumedAt).toEqual(producedAt)

                // Both members did real work after the split.
                expect(
                    new Set(ledger.filter((e) => wave2.some((r) => r.value === e.value)).map((e) => e.consumerId)).size
                ).toBe(2)
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        it('a batch in flight at revoke skips its offset store (generation guard): moved partition redelivers it, retained partition does not', async () => {
            const topic = `v2_int_reb_gen_${randomUUID()}`
            const groupId = `v2-int-reb-gen-${randomUUID()}`
            await createTopic(topic, 2)

            // The generation guard only engages when the loop processes the REVOKE while a task
            // is still in flight. With the default of 1 background slot, backpressure blocks the
            // loop on that very task (no polling → no rebalance callback → the task settles and
            // stores before the generation ever bumps). Give the loop free slots so it can take
            // the revoke while the gated task is pending — the scenario the guard exists for.
            const savedMaxBackgroundTasks = defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS
            defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS = 4

            const ledger: LedgerEntry[] = []
            // Gate for consumer A's background tasks: once armed, A's batches don't settle
            // until the test releases them — keeping their offset stores in flight across
            // the revoke so the generation guard is what decides their fate.
            let gateArmed = false
            let releaseGate: () => void = () => {}
            const gate = new Promise<void>((resolve) => {
                releaseGate = resolve
            })

            const recordA = (messages: Message[]): { backgroundTask?: Promise<unknown> } => {
                for (const m of messages) {
                    ledger.push({
                        consumerId: 'A',
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                }
                return gateArmed ? { backgroundTask: gate } : {}
            }
            const recordB = (messages: Message[]): void => {
                for (const m of messages) {
                    ledger.push({
                        consumerId: 'B',
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                }
            }

            const consumerA = makeConsumer(groupId, topic, (msgs) => Promise.resolve(recordA(msgs)), {
                autoOffsetStore: true,
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)

                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)

                const preGateCommit = new Map<number, number>()
                for (const partition of [0, 1]) {
                    const highest = Math.max(...wave1.filter((r) => r.partition === partition).map((r) => r.offset))
                    preGateCommit.set(partition, highest + 1)
                    await waitForAsync(
                        async () => (await fetchCommittedOffset(groupId, topic, partition)) === highest + 1,
                        10_000
                    )
                }

                // One gated message per partition: consumed by A, but its settle chain (and
                // therefore its offset store) hangs on the gate.
                gateArmed = true
                const gated = await produceTracked(producer, topic, [
                    { key: 'gated-p0', partition: 0 },
                    { key: 'gated-p1', partition: 1 },
                ])
                await waitFor(() => gated.every((g) => ledger.some((e) => e.value === g.value)), 8_000)

                // B joins while the gated batch is still in flight. The revoke bumps the
                // generation and drains — the drain blocks on our gate. Hold it long enough
                // for the revoke to be firmly in progress, then release.
                consumerB = makeConsumer(groupId, topic, (msgs) => Promise.resolve(recordB(msgs)), {
                    autoOffsetStore: true,
                })
                const b = consumerB
                await delay(8_000)
                releaseGate()

                await waitFor(() => consumerA.assignments().length === 1 && b.assignments().length === 1, 15_000)
                const movedPartition = b.assignments()[0].partition
                const retainedPartition = movedPartition === 0 ? 1 : 0

                // The generation guard skipped the gated batch's store, so the moved partition's
                // gated message is redelivered to B from the pre-gate commit point: seen exactly
                // twice overall (once by A pre-revoke, once by B). The retained partition stays
                // with A, whose in-memory position is already past its gated message: exactly once.
                const gatedMoved = gated.find((g) => g.partition === movedPartition)!
                const gatedRetained = gated.find((g) => g.partition === retainedPartition)!
                await waitFor(() => ledger.filter((e) => e.value === gatedMoved.value).length >= 2, 15_000)
                expect(
                    ledger
                        .filter((e) => e.value === gatedMoved.value)
                        .map((e) => e.consumerId)
                        .sort()
                ).toEqual(['A', 'B'])
                expect(ledger.filter((e) => e.value === gatedRetained.value).map((e) => e.consumerId)).toEqual(['A'])

                // Commits reflect the guard exactly: the retained partition's commit is still the
                // pre-gate mark (its gated store was skipped and nothing re-stored it), while the
                // moved partition advances past the gated message once B's redelivery settles.
                await waitForAsync(
                    async () => (await fetchCommittedOffset(groupId, topic, movedPartition)) === gatedMoved.offset + 1,
                    15_000
                )
                expect(await fetchCommittedOffset(groupId, topic, retainedPartition)).toBe(
                    preGateCommit.get(retainedPartition)
                )
            } finally {
                defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS = savedMaxBackgroundTasks
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })
    })

    // The session replay mode: autoCommit stays on but nothing is stored automatically, so
    // offsets reach the broker only when a flush stores them explicitly — here, the revoke hook.
    describe('autoOffsetStore off: offsets stored only by the revoke hook (replay-style)', () => {
        // The flush-on-revoke contract the session replay consumer relies on, at v2's cooperative
        // protocol. The flush deliberately outlives session.timeout.ms (6s): the background
        // heartbeat thread must keep the member alive for its whole duration — a slow flush is
        // bounded by max.poll.interval.ms, never the session timeout. The long window also gives
        // an unassign racing ahead of the hook ample time to manifest.
        it('flush-on-revoke outliving the session timeout: hook runs while assigned, stored offsets commit, no reprocessing', async () => {
            const flushDurationMs = 7_000
            const topic = `v2_int_reb_hook_${randomUUID()}`
            const groupId = `v2-int-reb-hook-${randomUUID()}`
            await createTopic(topic, 2)

            const ledger: LedgerEntry[] = []
            const trackedHighest = new Map<number, number>()
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
                    trackedHighest.set(m.partition, Math.max(trackedHighest.get(m.partition) ?? -1, m.offset))
                }
                return Promise.resolve()
            }

            const consumerA = makeConsumer(groupId, topic, record('A'), {
                autoOffsetStore: false,
                onPartitionsRevoked: async (revoked) => {
                    if (++hook.invocations > 1) {
                        return
                    }
                    hook.revokedPartitions = revoked.map((tp) => ({ topic: tp.topic, partition: tp.partition }))
                    hook.assignedOnEntry = consumerA.assignments().length
                    // The simulated flush: widens the revoke window so an unassign racing
                    // ahead of the hook reliably manifests — as a shrunken assignment or a
                    // store error below.
                    await delay(flushDurationMs)
                    hook.assignedAfterDelay = consumerA.assignments().length
                    try {
                        // Like the real ingester's flush: store offsets for everything tracked,
                        // not just the partitions being revoked.
                        consumerA.offsetsStore(
                            [...trackedHighest.entries()].map(([partition, offset]) => ({
                                topic,
                                partition,
                                offset: offset + 1,
                            }))
                        )
                    } catch (e) {
                        hook.storeError = e
                    }
                    hook.completedAt = Date.now()
                },
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)

                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 4 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 4 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)

                // Precondition: autoOffsetStore is off and nothing was stored, so nothing is
                // committed — only the hook's store can move the group offsets.
                for (const partition of [0, 1]) {
                    expect(await fetchCommittedOffset(groupId, topic, partition)).toBeNull()
                }

                consumerB = makeConsumer(groupId, topic, record('B'), { autoOffsetStore: false })
                const b = consumerB

                await waitFor(() => hook.completedAt > 0, 15_000)

                // Cooperative revoke: exactly one partition moves, and A still owns BOTH
                // partitions for the whole duration of the flush.
                expect(hook.revokedPartitions).toHaveLength(1)
                expect(hook.assignedOnEntry).toBe(2)
                expect(hook.assignedAfterDelay).toBe(2)
                expect(hook.storeError).toBeNull()

                await waitFor(() => consumerA.assignments().length === 1 && b.assignments().length === 1, 15_000)
                const movedPartition = b.assignments()[0].partition

                // The moved partition's stored offset is committed as part of the unassign;
                // the retained partition's store lands via the auto-commit timer. Both exact.
                const expectedCommit = new Map<number, number>()
                for (const partition of [0, 1]) {
                    const highest = Math.max(...wave1.filter((r) => r.partition === partition).map((r) => r.offset))
                    expectedCommit.set(partition, highest + 1)
                }
                for (const partition of [movedPartition, movedPartition === 0 ? 1 : 0]) {
                    await waitForAsync(
                        async () =>
                            (await fetchCommittedOffset(groupId, topic, partition)) === expectedCommit.get(partition),
                        15_000
                    )
                }

                // The new owner resumes after the flushed offsets: a second wave lands
                // contiguously and nothing from the first wave is ever redelivered.
                const wave2 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${4 + i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${4 + i}`, partition: 1 })),
                ])
                for (const partition of [0, 1]) {
                    expect(Math.min(...wave2.filter((r) => r.partition === partition).map((r) => r.offset))).toBe(
                        expectedCommit.get(partition)
                    )
                }

                const produced = [...wave1, ...wave2]
                await waitFor(() => countByPartitionOffset(ledger).size >= produced.length, 15_000)
                expect(ledger.length).toBe(produced.length)
                const consumedAt = new Map(
                    ledger.map((e) => [`${e.partition}:${e.offset}`, { key: e.key, value: e.value }])
                )
                const producedAt = new Map(
                    produced.map((r) => [`${r.partition}:${r.offset}`, { key: r.key, value: r.value }])
                )
                expect(consumedAt).toEqual(producedAt)
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        it('a throwing revoke hook still releases the partition: moved partition reprocesses, retained partition is unaffected', async () => {
            const topic = `v2_int_reb_hookthrow_${randomUUID()}`
            const groupId = `v2-int-reb-hookthrow-${randomUUID()}`
            await createTopic(topic, 2)

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

            const consumerA = makeConsumer(groupId, topic, record('A'), {
                autoOffsetStore: false,
                onPartitionsRevoked: () => {
                    throw new Error('flush failed during revoke')
                },
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)
                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)

                consumerB = makeConsumer(groupId, topic, record('B'), { autoOffsetStore: false })
                const b = consumerB

                // The hook threw, so nothing was stored — but the partition must still be given
                // up. The new owner starts from earliest and redelivers the moved partition's
                // wave; the retained partition stays with A and is never re-read.
                await waitFor(() => consumerA.assignments().length === 1 && b.assignments().length === 1, 20_000)
                const movedPartition = b.assignments()[0].partition
                const retainedPartition = movedPartition === 0 ? 1 : 0
                const movedHighest = Math.max(
                    ...wave1.filter((r) => r.partition === movedPartition).map((r) => r.offset)
                )

                await waitFor(
                    () =>
                        ledger.filter(
                            (e) => e.consumerId === 'B' && e.partition === movedPartition && e.offset === movedHighest
                        ).length >= 1,
                    15_000
                )
                for (const r of wave1) {
                    const expectedCount = r.partition === movedPartition ? 2 : 1
                    expect(ledger.filter((e) => e.value === r.value)).toHaveLength(expectedCount)
                }
                expect(await fetchCommittedOffset(groupId, topic, retainedPartition)).toBeNull()
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        it('a flush exceeding the consumer budget: the hook is abandoned, the rebalance proceeds, the member survives unfenced', async () => {
            const topic = `v2_int_reb_hookabandon_${randomUUID()}`
            const groupId = `v2-int-reb-hookabandon-${randomUUID()}`
            await createTopic(topic, 2)

            // The consumer-side budget for the revoke hook (drainTimeoutMs), well under
            // max.poll.interval.ms (30s here): the consumer gives the partitions up itself, so
            // the member must NOT get fenced — it keeps its retained partition and stays live.
            // The flush outlives the budget by enough that the takeover assertions all land
            // while it is still running.
            const hookBudgetMs = 3_000
            const flushDurationMs = 15_000
            const savedRebalanceTimeout = defaultConfig.CONSUMER_REBALANCE_TIMEOUT_MS
            defaultConfig.CONSUMER_REBALANCE_TIMEOUT_MS = hookBudgetMs

            const ledger: LedgerEntry[] = []
            const tracked = new Map<number, number>()
            const hook = { invocations: 0, completedAt: 0 }

            const record = (consumerId: string, track: boolean) => (messages: Message[]) => {
                for (const m of messages) {
                    ledger.push({
                        consumerId,
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                    if (track) {
                        tracked.set(m.partition, Math.max(tracked.get(m.partition) ?? 0, m.offset + 1))
                    }
                }
                return Promise.resolve()
            }

            const consumerA = makeConsumer(groupId, topic, record('A', true), {
                autoOffsetStore: false,
                onPartitionsRevoked: async () => {
                    if (++hook.invocations > 1) {
                        return
                    }
                    await delay(flushDurationMs)
                    // The abandoned flush finally stores its tracked offsets. For the moved
                    // partition this must never become a group commit — the new owner already
                    // reprocessed instead.
                    try {
                        consumerA.offsetsStore(
                            [...tracked.entries()].map(([partition, offset]) => ({ topic, partition, offset }))
                        )
                    } catch {
                        // Rejection of the moved partition's store is an acceptable outcome too.
                    }
                    hook.completedAt = Date.now()
                },
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)
                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)
                for (const partition of [0, 1]) {
                    expect(await fetchCommittedOffset(groupId, topic, partition)).toBeNull()
                }

                consumerB = makeConsumer(groupId, topic, record('B', false), { autoOffsetStore: false })
                const b = consumerB

                // The budget releases the rebalance: B owns the moved partition and (with no
                // committed offsets) redelivers its wave while the flush is still running.
                await waitFor(
                    () => consumerA.assignments().length === 1 && b.assignments().length === 1,
                    hookBudgetMs + 10_000
                )
                const movedPartition = b.assignments()[0].partition
                const retainedPartition = movedPartition === 0 ? 1 : 0
                await waitFor(
                    () =>
                        wave1
                            .filter((r) => r.partition === movedPartition)
                            .every((r) =>
                                ledger.some(
                                    (e) => e.consumerId === 'B' && e.partition === r.partition && e.offset === r.offset
                                )
                            ),
                    12_000
                )
                expect(hook.completedAt).toBe(0)

                // Unlike the fencing case, the member survives: it keeps the retained partition
                // and keeps consuming new messages on it while the flush is still in progress.
                const wave2 = await produceTracked(producer, topic, [
                    { key: 'retained-post', partition: retainedPartition },
                ])
                await waitFor(() => ledger.some((e) => e.consumerId === 'A' && e.value === wave2[0].value), 10_000)
                expect(consumerA.assignments().length).toBe(1)

                // Once the flush finishes, its late store for the moved partition is discarded:
                // the group offset stays unset (B stored nothing; A no longer owns it).
                await waitFor(() => hook.completedAt > 0, flushDurationMs + 10_000)
                await delay(1_500)
                expect(await fetchCommittedOffset(groupId, topic, movedPartition)).toBeNull()
            } finally {
                defaultConfig.CONSUMER_REBALANCE_TIMEOUT_MS = savedRebalanceTimeout
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        it('a flush exceeding the rebalance timeout: the broker fences the slow member, the new owner reprocesses, the slow consumer recovers', async () => {
            const topic = `v2_int_reb_hookslow_${randomUUID()}`
            const groupId = `v2-int-reb-hookslow-${randomUUID()}`
            await createTopic(topic, 2)

            // max.poll.interval.ms doubles as the broker-enforced rebalance timeout: a member
            // that hasn't rejoined within it is kicked and the rebalance completes without it.
            // 6s is the tightest legal value — librdkafka requires it >= session.timeout.ms,
            // whose broker-enforced floor is 6s. The flush outlives it by enough that B holds
            // both partitions for several seconds mid-flush (once the flush ends, A rejoins and
            // takes a partition back — the redelivery assertions need the sole-owner window).
            const rebalanceTimeoutMs = 6_000
            const flushDurationMs = 12_000

            const ledger: LedgerEntry[] = []
            const tracked = new Map<number, number>()
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
                    if (consumerId === 'A') {
                        tracked.set(m.partition, Math.max(tracked.get(m.partition) ?? 0, m.offset + 1))
                    }
                }
                return Promise.resolve()
            }

            const consumerA = makeConsumer(groupId, topic, record('A'), {
                autoOffsetStore: false,
                onPartitionsRevoked: async () => {
                    if (++hook.invocations > 1) {
                        return
                    }
                    await delay(flushDurationMs)
                    // Like a real slow flush, store the tracked offsets once it finally completes —
                    // the member has been fenced by now, and the test asserts this late store never
                    // becomes a group commit (the new owner already reprocessed instead).
                    try {
                        consumerA.offsetsStore(
                            [...tracked.entries()].map(([partition, offset]) => ({ topic, partition, offset }))
                        )
                    } catch {
                        // Rejection is fine — either outcome must leave the group offsets unset.
                    }
                    hook.completedAt = Date.now()
                },
                rdKafkaOverrides: { 'max.poll.interval.ms': rebalanceTimeoutMs },
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)
                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.filter((e) => e.consumerId === 'A').length >= wave1.length, 8_000)

                consumerB = makeConsumer(groupId, topic, record('B'), {
                    autoOffsetStore: false,
                    rdKafkaOverrides: { 'max.poll.interval.ms': rebalanceTimeoutMs },
                })

                // The fenced member is kicked entirely, so B takes over BOTH partitions and
                // (with nothing committed) redelivers the first wave while A's flush is still
                // in progress: a slow flush delays the rebalance only up to the rebalance
                // timeout, never indefinitely.
                await waitFor(
                    () =>
                        wave1.every((r) =>
                            ledger.some(
                                (e) => e.consumerId === 'B' && e.partition === r.partition && e.offset === r.offset
                            )
                        ),
                    rebalanceTimeoutMs + 10_000
                )
                expect(hook.completedAt).toBe(0)
                for (const partition of [0, 1]) {
                    expect(await fetchCommittedOffset(groupId, topic, partition)).toBeNull()
                }

                // The slow consumer must recover rather than wedge: once the flush finishes,
                // newly produced messages are still consumed.
                await waitFor(() => hook.completedAt > 0, flushDurationMs + 10_000)
                const wave2 = await produceTracked(producer, topic, [
                    { key: 'a-post', partition: 0 },
                    { key: 'b-post', partition: 1 },
                ])
                await waitFor(() => wave2.every((r) => ledger.some((e) => e.value === r.value)), 20_000)

                // The fenced flush's late offset store never becomes a group commit: nothing in
                // this test stores offsets successfully, so the group offsets must still be unset.
                for (const partition of [0, 1]) {
                    expect(await fetchCommittedOffset(groupId, topic, partition)).toBeNull()
                }
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        it('a flushed batch then a batch in flight at revoke: commits advance from the flushed mark to the revoke mark, never backwards', async () => {
            const topic = `v2_int_reb_twocycle_${randomUUID()}`
            const groupId = `v2-int-reb-twocycle-${randomUUID()}`
            await createTopic(topic, 2)

            const ledger: LedgerEntry[] = []
            // Replay-style offset manager: track next-to-process per partition (monotonic), store
            // everything tracked on flush, clear so the next cycle starts fresh.
            const tracked = new Map<number, number>()
            const flushOffsets = (): { partition: number; offset: number }[] => {
                const stored = [...tracked.entries()].map(([partition, offset]) => ({ topic, partition, offset }))
                tracked.clear()
                if (stored.length > 0) {
                    consumerA.offsetsStore(stored)
                }
                return stored.map(({ partition, offset }) => ({ partition, offset }))
            }
            const hook: {
                invocations: number
                storedAtRevoke: { partition: number; offset: number }[]
                completedAt: number
            } = {
                invocations: 0,
                storedAtRevoke: [],
                completedAt: 0,
            }

            const record = (consumerId: string, track: boolean) => (messages: Message[]) => {
                for (const m of messages) {
                    ledger.push({
                        consumerId,
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                    if (track) {
                        tracked.set(m.partition, Math.max(tracked.get(m.partition) ?? 0, m.offset + 1))
                    }
                }
                return Promise.resolve()
            }

            const consumerA = makeConsumer(groupId, topic, record('A', true), {
                autoOffsetStore: false,
                onPartitionsRevoked: () => {
                    if (++hook.invocations === 1) {
                        hook.storedAtRevoke = flushOffsets()
                        hook.completedAt = Date.now()
                    }
                    return Promise.resolve()
                },
            })
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)

                // Cycle 1: consumed, then flushed normally (the periodic size/age flush) — the
                // stored offsets reach the broker via the auto-commit timer.
                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)
                const flush1 = flushOffsets()
                const mark1 = new Map(flush1.map(({ partition, offset }) => [partition, offset]))
                for (const partition of [0, 1]) {
                    await waitForAsync(
                        async () => (await fetchCommittedOffset(groupId, topic, partition)) === mark1.get(partition),
                        10_000
                    )
                }

                // Cycle 2: in flight at the revoke — produced to partition 0 only, so the flush the
                // revoke hook runs must advance partition 0 and leave partition 1 exactly at its
                // cycle-1 mark (tracked state was cleared by the first flush).
                const wave2 = await produceTracked(
                    producer,
                    topic,
                    Array.from({ length: 3 }, (_, i) => ({ key: `a${3 + i}`, partition: 0 }))
                )
                await waitFor(() => wave2.every((r) => ledger.some((e) => e.value === r.value)), 8_000)
                const mark2 = Math.max(...wave2.map((r) => r.offset)) + 1

                consumerB = makeConsumer(groupId, topic, record('B', false), { autoOffsetStore: false })
                const b = consumerB
                await waitFor(() => hook.completedAt > 0, 15_000)

                // The revoke flush stored exactly the in-flight cycle: partition 0 at its new mark,
                // nothing for partition 1.
                expect(hook.storedAtRevoke).toEqual([{ partition: 0, offset: mark2 }])

                await waitFor(() => consumerA.assignments().length === 1 && b.assignments().length === 1, 15_000)

                // Commits advance, never rewind: partition 0 moves from mark1 to mark2 (the unassign
                // or timer commits the newer store over the earlier cycle-1 commit), partition 1
                // stays exactly at mark1.
                await waitForAsync(async () => (await fetchCommittedOffset(groupId, topic, 0)) === mark2, 15_000)
                expect(await fetchCommittedOffset(groupId, topic, 1)).toBe(mark1.get(1))

                // Resumption is exact on both partitions: a third wave lands contiguously and every
                // message across all three cycles was delivered exactly once — neither flushed cycle
                // is ever reprocessed, regardless of which partition moved.
                const wave3 = await produceTracked(producer, topic, [
                    { key: 'a-final', partition: 0 },
                    { key: 'b-final', partition: 1 },
                ])
                expect(Math.min(...wave3.filter((r) => r.partition === 0).map((r) => r.offset))).toBe(mark2)
                expect(Math.min(...wave3.filter((r) => r.partition === 1).map((r) => r.offset))).toBe(mark1.get(1))

                const produced = [...wave1, ...wave2, ...wave3]
                await waitFor(() => countByPartitionOffset(ledger).size >= produced.length, 15_000)
                expect(ledger.length).toBe(produced.length)
                const consumedAt = new Map(ledger.map((e) => [`${e.partition}:${e.offset}`, e.value]))
                const producedAt = new Map(produced.map((r) => [`${r.partition}:${r.offset}`, r.value]))
                expect(consumedAt).toEqual(producedAt)
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })

        // The flush-on-stop contract the session replay consumer's shutdown relies on:
        // stopConsuming() → final flush stores offsets → disconnect() commits them leaving the
        // group. The batch in flight when stopConsuming is called must settle before it resolves,
        // and nothing may be consumed after it — otherwise the final flush races live intake.
        it('shutdown flush: stopConsuming drains in-flight work and halts intake, offsets stored before disconnect commit exactly', async () => {
            const topic = `v2_int_reb_stop_${randomUUID()}`
            const groupId = `v2-int-reb-stop-${randomUUID()}`
            await createTopic(topic, 2)

            const ledger: LedgerEntry[] = []
            // Replay-style offset manager: track next-to-process per partition; the shutdown
            // flush stores everything tracked between stopConsuming and disconnect.
            const tracked = new Map<number, number>()
            // Once armed, batches don't settle until the test releases them — keeping a batch
            // in flight across the stopConsuming call.
            let gateArmed = false
            let releaseGate: () => void = () => {}
            const gate = new Promise<void>((resolve) => {
                releaseGate = resolve
            })

            const record = (consumerId: string, track: boolean) => (messages: Message[]) => {
                for (const m of messages) {
                    ledger.push({
                        consumerId,
                        partition: m.partition,
                        offset: m.offset,
                        key: m.key?.toString() ?? '',
                        value: m.value?.toString() ?? '',
                        seenAt: Date.now(),
                    })
                    if (track) {
                        tracked.set(m.partition, Math.max(tracked.get(m.partition) ?? 0, m.offset + 1))
                    }
                }
            }

            const consumerA = makeConsumer(
                groupId,
                topic,
                (messages) => {
                    record('A', true)(messages)
                    return Promise.resolve(gateArmed ? { backgroundTask: gate } : {})
                },
                { autoOffsetStore: false }
            )
            let consumerB: KafkaConsumerV2 | undefined

            try {
                await waitFor(() => consumerA.assignments().length === 2, 10_000)

                const wave1 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${i}`, partition: 1 })),
                ])
                await waitFor(() => ledger.length >= wave1.length, 8_000)

                // One gated message: consumed, but its settle chain hangs on the gate, so its
                // batch is still in flight when stopConsuming is called.
                gateArmed = true
                const gated = await produceTracked(producer, topic, [{ key: 'gated-p0', partition: 0 }])
                await waitFor(() => ledger.some((e) => e.value === gated[0].value), 8_000)

                // stopConsuming must not resolve while the in-flight batch is pending — the
                // drain guarantee the shutdown flush depends on.
                let stopSettled = false
                const stopPromise = consumerA.stopConsuming().then(() => {
                    stopSettled = true
                })
                await delay(1_500)
                expect(stopSettled).toBe(false)
                releaseGate()
                await stopPromise

                // Intake is halted for good: messages produced after stopConsuming are never
                // consumed by A, even though it is still connected and owns the partitions.
                const wave2 = await produceTracked(producer, topic, [
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `a${4 + i}`, partition: 0 })),
                    ...Array.from({ length: 3 }, (_, i) => ({ key: `b${3 + i}`, partition: 1 })),
                ])
                await delay(2_000)
                expect(ledger.filter((e) => wave2.some((r) => r.value === e.value))).toEqual([])

                // The shutdown flush window: the store must succeed (the partitions are still
                // owned), and disconnect commits it as the member leaves the group.
                consumerA.offsetsStore(
                    [...tracked.entries()].map(([partition, offset]) => ({ topic, partition, offset }))
                )
                await consumerA.disconnect()

                const expectedCommit = new Map(tracked)
                for (const partition of [0, 1]) {
                    await waitForAsync(
                        async () =>
                            (await fetchCommittedOffset(groupId, topic, partition)) === expectedCommit.get(partition),
                        10_000
                    )
                }

                // A restart resumes exactly after the shutdown flush: the new consumer sees
                // wave2 only — nothing the flush covered is redelivered — each message exactly
                // once at the offset its delivery report announced.
                consumerB = makeConsumer(groupId, topic, (msgs) => Promise.resolve(record('B', false)(msgs)), {
                    autoOffsetStore: false,
                })
                await waitFor(
                    () => wave2.every((r) => ledger.some((e) => e.consumerId === 'B' && e.value === r.value)),
                    15_000
                )
                const bEntries = ledger.filter((e) => e.consumerId === 'B')
                expect(bEntries).toHaveLength(wave2.length)
                expect(new Map(bEntries.map((e) => [`${e.partition}:${e.offset}`, e.value]))).toEqual(
                    new Map(wave2.map((r) => [`${r.partition}:${r.offset}`, r.value]))
                )
            } finally {
                await consumerA.disconnect()
                await consumerB?.disconnect()
                await deleteTopic(topic)
            }
        })
    })
})
