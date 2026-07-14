import {
    AdminClient,
    LibrdKafkaError,
    Message,
    KafkaConsumer as RdKafkaConsumer,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { randomUUID } from 'node:crypto'

import { delay } from '../../utils/utils'
import { KafkaProducerWrapper } from '../producer'
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
 *    leaving offsets uncommitted so the new owner reprocesses (at-least-once).
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
    seenAt: number
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
    onPartitionsRevoked?: (assignments: { topic: string; partition: number }[]) => Promise<void>
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
        }
    )
    void consumer.connect(eachBatch, onPartitionsRevoked).catch((err: unknown) => {
        throw new Error(`Consumer failed to connect: ${String(err)}`)
    })
    return consumer
}

describe('KafkaConsumer v1 revoke wind-down (integration)', () => {
    let producer: KafkaProducerWrapper

    beforeAll(async () => {
        producer = await KafkaProducerWrapper.createWithConfig(undefined, KAFKA_CONFIG as Record<string, unknown>)
    })

    afterAll(async () => {
        await producer.disconnect()
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
                    ledger.push({ consumerId, partition: m.partition, offset: m.offset, seenAt: Date.now() })
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
                await produceMessages(producer, topic, 10)
                await waitFor(() => ledger.length >= 10, 8_000)

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

                // The offsets stored during the hook are committed as part of the unassign,
                // with the exact commit semantics (highest consumed offset + 1).
                await waitForAsync(async () => (await fetchCommittedOffset(groupId, topic, 0)) === 10, 15_000)

                // The settled owner resumes after the committed offset: the second wave is
                // consumed, and none of the first wave is ever delivered again.
                await produceMessages(producer, topic, 5)
                await waitFor(() => new Set(ledger.map((e) => e.offset)).size >= 15, 15_000)

                const countsByOffset = new Map<number, number>()
                for (const e of ledger) {
                    countsByOffset.set(e.offset, (countsByOffset.get(e.offset) ?? 0) + 1)
                }
                for (const [offset, count] of countsByOffset) {
                    expect({ offset, count }).toEqual({ offset, count: 1 })
                }
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
                ledger.push({ consumerId, partition: m.partition, offset: m.offset, seenAt: Date.now() })
            }
            return Promise.resolve()
        }

        const consumerA = makeConsumer(groupId, topic, record('A'), () => {
            throw new Error('flush failed during revoke')
        })
        let consumerB: KafkaConsumer | undefined

        try {
            await waitFor(() => consumerA.assignments().length > 0, 10_000)
            await produceMessages(producer, topic, 10)
            await waitFor(() => ledger.filter((e) => e.consumerId === 'A').length >= 10, 8_000)

            consumerB = makeConsumer(groupId, topic, record('B'), () => Promise.resolve())

            // The hook threw, so no offsets were stored; the partitions must still be given up
            // and the rebalance complete. The new owner (either member) starts from earliest and
            // redelivers the first wave — consumption resuming at all is the proof the group
            // wasn't stranded, redelivery is the expected at-least-once fallout.
            await waitFor(() => ledger.filter((e) => e.offset === 9).length >= 2, 20_000)
            expect(await fetchCommittedOffset(groupId, topic, 0)).toBeNull()
        } finally {
            await consumerA.disconnect()
            await consumerB?.disconnect()
            await deleteTopic(topic)
        }
    })
})
