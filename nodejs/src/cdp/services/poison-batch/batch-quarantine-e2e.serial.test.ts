import { randomUUID } from 'crypto'
import { AdminClient, Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaConsumerV2 } from '~/common/kafka/consumer/consumer-v2'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { waitForExpect } from '~/tests/helpers/expectations'
import { deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'

import { CyclotronJobInvocation, CyclotronJobQueueKind, DEAD_LETTER_QUEUE } from '../../types'
import { CyclotronJobQueueKafka } from '../job-queue/job-queue-kafka'
import { CrashGuard, CrashGuardSettings, batchAttemptsKey, createCrashGuardSettings } from './crash-guard'
import { divertToDeadLetter } from './divert-to-dead-letter'

const MAX_ATTEMPTS = 2
const DIVERT_TOPIC = `cdp_cyclotron_${DEAD_LETTER_QUEUE}`

type ConsumeBatch = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<unknown> }>

describe('CDP batch quarantine against Kafka and Valkey', () => {
    jest.setTimeout(120_000)

    const usedV2 = defaultConfig.CONSUMER_USE_V2
    let producer: KafkaProducerWrapper
    let kind: CyclotronJobQueueKind
    let topic: string
    let group: string
    let workers: CyclotronJobQueueKafka[]
    let processed: string[]
    let poison: { key: string; value: string; headers: Record<string, string> }

    beforeAll(async () => {
        defaultConfig.CONSUMER_USE_V2 = true
        producer = await KafkaProducerWrapper.create(undefined)
    })

    afterAll(async () => {
        defaultConfig.CONSUMER_USE_V2 = usedV2
        await producer.disconnect()
    })

    beforeEach(async () => {
        // The worker reads cdp_cyclotron_<queue> as group cdp-cyclotron-<queue>-consumer. A queue name of
        // its own gives each test a fresh topic and group, so nothing a previous run left behind is read.
        kind = `batch_quarantine_e2e_${randomUUID().replace(/-/g, '')}` as CyclotronJobQueueKind
        topic = `cdp_cyclotron_${kind}`
        group = `cdp-cyclotron-${kind}-consumer`
        workers = []
        processed = []
        poison = { key: randomUUID(), value: 'not-json', headers: { teamId: '2', functionId: 'poisoned-fn' } }
        await ensureKafkaTopics([topic, DIVERT_TOPIC])
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await Promise.all(workers.map(stopWorker))
        await deleteKafkaTopics([topic])
    })

    const quarantineFor = (mode: CrashGuardSettings['mode']): CrashGuardSettings =>
        createCrashGuardSettings({
            ...defaultConfig,
            CDP_BATCH_QUARANTINE_MODE: mode,
            CDP_BATCH_QUARANTINE_MAX_ATTEMPTS: MAX_ATTEMPTS,
            CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS: 300,
        })!

    const recordProcessed: ConsumeBatch = (invocations) => {
        processed.push(...invocations.map((invocation) => invocation.id))
        return Promise.resolve({ backgroundTask: Promise.resolve() })
    }

    const startWorker = async (
        quarantine: CrashGuardSettings,
        consumeBatch: ConsumeBatch = recordProcessed
    ): Promise<CyclotronJobQueueKafka> => {
        const worker = new CyclotronJobQueueKafka(undefined, defaultConfig, defaultConfig.CONSUMER_BATCH_SIZE)
        workers.push(worker)
        await worker.startAsProducer()
        await worker.startAsConsumer(kind, consumeBatch, {
            crashGuard: ({ groupId, produce }) =>
                new CrashGuard(quarantine, groupId, divertToDeadLetter(produce, groupId)),
        })
        return worker
    }

    const stopWorker = async (worker: CyclotronJobQueueKafka): Promise<void> => {
        workers = workers.filter((x) => x !== worker)
        await worker.stopConsumer()
        await worker.stopProducer()
    }

    const crashOf = async (worker: CyclotronJobQueueKafka): Promise<unknown> => {
        const consumer = worker['kafkaConsumer']
        const loop: Promise<void> =
            consumer instanceof KafkaConsumerV2 ? consumer['loopDone']! : (consumer as KafkaConsumer)['consumerLoop']!
        let crash: unknown
        loop.catch((error) => {
            crash = error
        })
        await waitForExpect(() => expect(crash).toBeDefined(), 30_000)
        return crash
    }

    const crashLoop = async (
        quarantine: CrashGuardSettings,
        restarts: number,
        consumeBatch?: ConsumeBatch
    ): Promise<unknown[]> => {
        const crashes: unknown[] = []
        for (let i = 0; i < restarts; i++) {
            const worker = await startWorker(quarantine, consumeBatch)
            crashes.push(await crashOf(worker))
            await stopWorker(worker)
        }
        return crashes
    }

    type TestMessage = { key: string; value: string; headers?: Record<string, string>; partition?: number }

    const produce = (message: TestMessage): Promise<void> =>
        producer.produce({ topic, ...message, value: Buffer.from(message.value) })

    const invocation = (id: string): string =>
        JSON.stringify({ id, teamId: 2, functionId: 'healthy-fn', state: {}, queue: kind, queuePriority: 0 })

    const produceInvocation = async (partition?: number): Promise<string> => {
        const id = randomUUID()
        await produce({ key: id, value: invocation(id), partition })
        return id
    }

    // Reads the whole dead letter topic up to its current end, so an empty result means nothing was diverted.
    const divertedWithKey = async (key: string): Promise<Message[]> => {
        const reader = new KafkaConsumerV2({
            groupId: `batch-quarantine-e2e-read-${randomUUID()}`,
            topic: DIVERT_TOPIC,
            autoCommit: false,
            batchTimeoutMs: 50,
        })
        const read: Message[] = []
        await reader.connect((batch) => {
            read.push(...batch)
            return Promise.resolve()
        })
        try {
            const partitions = await reader.getPartitionsForTopic(DIVERT_TOPIC)
            const ends = await Promise.all(
                partitions.map(async ({ id }) => ({
                    id,
                    end: (await reader.queryWatermarkOffsets(DIVERT_TOPIC, id))[1],
                }))
            )
            await waitForExpect(() => {
                for (const { id, end } of ends.filter((x) => x.end > 0)) {
                    expect(read.some((m) => m.partition === id && m.offset >= end - 1)).toBe(true)
                }
            }, 30_000)
        } finally {
            await reader.disconnect()
        }
        return read.filter((m) => m.key?.toString() === key)
    }

    const counter = async (name: string, labels: Record<string, string>): Promise<number> =>
        (await register.getSingleMetric(name)!.get()).values.find((v) =>
            Object.entries(labels).every(([k, value]) => v.labels[k] === value)
        )?.value ?? 0

    const storedAttempts = (
        quarantine: CrashGuardSettings,
        partition: number,
        offset: number
    ): Promise<string | null> =>
        quarantine.valkey.useClient({ name: 'test' }, (client) =>
            client.hget(batchAttemptsKey(group, partition, offset), 'attempts')
        )

    const growTopic = async (partitions: number): Promise<void> => {
        const admin = AdminClient.create({
            'client.id': 'batch-quarantine-e2e',
            'metadata.broker.list': defaultConfig.KAFKA_HOSTS,
        })
        try {
            await new Promise<void>((resolve, reject) =>
                admin.createPartitions(topic, partitions, 10_000, (error) => (error ? reject(error) : resolve()))
            )
        } finally {
            admin.disconnect()
        }
    }

    const asDiverted = (messages: Message[]): { value: string; headers: Record<string, string> }[] =>
        messages.map((m) => ({ value: m.value!.toString(), headers: parseKafkaHeaders(m.headers) }))

    it('diverts a batch that crashed the worker too often, then moves on and commits past it', async () => {
        const quarantine = quarantineFor('enforce')
        await produce(poison)

        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))

        let worker = await startWorker(quarantine)
        await waitForExpect(
            async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1),
            30_000
        )
        expect(asDiverted(await divertedWithKey(poison.key))).toEqual([
            { value: poison.value, headers: poison.headers },
        ])

        const healthy = await produceInvocation()
        await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)
        await stopWorker(worker)

        // Something new to wait for, because a restart that replays nothing is otherwise indistinguishable
        // from one that has not fetched yet.
        worker = await startWorker(quarantine)
        const later = await produceInvocation()
        await waitForExpect(() => expect(processed).toEqual([healthy, later]), 30_000)

        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(1)
        expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1)
        expect(await storedAttempts(quarantine, 0, 0)).toEqual(String(MAX_ATTEMPTS + 1))
    })

    it.each([
        ['v1', false],
        ['v2', true],
    ])('keeps crashing on the batch while the divert fails, with consumer %s', async (_, useV2) => {
        const configuredV2 = defaultConfig.CONSUMER_USE_V2
        defaultConfig.CONSUMER_USE_V2 = useV2
        try {
            const quarantine = quarantineFor('enforce')
            await produce(poison)
            expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))

            const dlqDown = new Error('hogdlq unavailable')
            const produceToKafka = KafkaProducerWrapper.prototype.produce
            const failDivert = jest.spyOn(KafkaProducerWrapper.prototype, 'produce').mockImplementation(function (
                this: KafkaProducerWrapper,
                message
            ) {
                return message.topic === DIVERT_TOPIC ? Promise.reject(dlqDown) : produceToKafka.call(this, message)
            })
            expect(await crashLoop(quarantine, 2)).toEqual([dlqDown, dlqDown])
            failDivert.mockRestore()

            await startWorker(quarantine)
            await waitForExpect(
                async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1),
                30_000
            )
            const healthy = await produceInvocation()
            await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)

            expect(asDiverted(await divertedWithKey(poison.key))).toEqual([
                { value: poison.value, headers: poison.headers },
            ])
            // Each restart counts one more attempt at offset 0, so a failed divert never moved the commit past it.
            expect(await storedAttempts(quarantine, 0, 0)).toEqual(String(MAX_ATTEMPTS + 3))
        } finally {
            defaultConfig.CONSUMER_USE_V2 = configuredV2
        }
    })

    it.each([
        ['v1', false],
        ['v2', true],
    ])(
        'takes back the attempt of a background task that outlives the guard timeout, with consumer %s',
        async (_, useV2) => {
            const configured = {
                useV2: defaultConfig.CONSUMER_USE_V2,
                timeoutMs: defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS,
            }
            defaultConfig.CONSUMER_USE_V2 = useV2
            // The guard gives up 2s earlier, after twice the 500ms Valkey timeout and a 1s margin.
            defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS = 4_000
            try {
                const quarantine = quarantineFor('enforce')
                const id = await produceInvocation()
                // A produce that librdkafka keeps retrying through a Kafka outage holds the background task. In
                // production consumer v2 exits the process on the timeout, so the task never finishes and no
                // success clears the count. The test cannot kill the process, so with v2 the task fails instead.
                const stalled: ConsumeBatch = (invocations) => {
                    if (invocations.length === 0) {
                        return recordProcessed(invocations)
                    }
                    processed.push(...invocations.map((invocation) => invocation.id))
                    const backgroundTask = new Promise((resolve, reject) =>
                        setTimeout(() => (useV2 ? reject(new Error('process exited')) : resolve(undefined)), 6_000)
                    )
                    return Promise.resolve({ backgroundTask })
                }

                if (useV2) {
                    // Consumer v2 gives up on the task and restarts, which reads as a crash without the take back.
                    const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1, stalled)
                    expect(crashes).toEqual(
                        Array(MAX_ATTEMPTS + 1).fill(
                            expect.objectContaining({ message: 'background_task_timeout_after_4000ms' })
                        )
                    )
                    expect(await storedAttempts(quarantine, 0, 0)).toEqual('0')
                } else {
                    // Consumer v1 waits for the task, so the take back leaves the batch running and clears the count once it finishes.
                    await startWorker(quarantine, stalled)
                    await waitForExpect(
                        async () => expect(await counter('cdp_batch_attempts_uncounted_total', { group })).toEqual(1),
                        30_000
                    )
                    expect(await storedAttempts(quarantine, 0, 0)).toEqual('0')
                    await waitForExpect(async () => expect(await storedAttempts(quarantine, 0, 0)).toBeNull(), 30_000)
                }
                expect(processed).toEqual(Array(useV2 ? MAX_ATTEMPTS + 1 : 1).fill(id))
                expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(0)
            } finally {
                defaultConfig.CONSUMER_USE_V2 = configured.useV2
                defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS = configured.timeoutMs
            }
        }
    )

    it('diverts a healthy partition together with the poisoned partition it was fetched with', async () => {
        await growTopic(2)
        const quarantine = quarantineFor('enforce')
        const healthyId = randomUUID()
        const healthy = {
            key: healthyId,
            value: invocation(healthyId),
            headers: { teamId: '2', functionId: 'healthy-fn' },
        }
        await produce({ ...poison, partition: 0 })
        await produce({ ...healthy, partition: 1 })

        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))
        // A count on partition 1 means each crashing fetch held both partitions. Had partition 1 come in a
        // fetch of its own, it would have been processed and its count cleared, or never been fetched at all.
        expect(await storedAttempts(quarantine, 1, 0)).toEqual(String(MAX_ATTEMPTS))

        await startWorker(quarantine)
        await waitForExpect(
            async () => expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(2),
            30_000
        )
        const later = [await produceInvocation(0), await produceInvocation(1)]
        await waitForExpect(() => expect([...processed].sort()).toEqual([...later].sort()), 30_000)

        expect(asDiverted(await divertedWithKey(healthyId))).toEqual([
            { value: healthy.value, headers: healthy.headers },
        ])
        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(2)
    })

    it('diverts a batch once when the worker crashes after the divert and before the commit', async () => {
        await growTopic(2)
        const quarantine = quarantineFor('enforce')
        await produce({ ...poison, partition: 0 })
        expect(await crashLoop(quarantine, MAX_ATTEMPTS)).toEqual(Array(MAX_ATTEMPTS).fill(expect.any(SyntaxError)))
        const healthy = await produceInvocation(1)

        const crashAfterDivert = new Error('worker crashed after the divert')
        let crashed = false
        const crashOnce: ConsumeBatch = (invocations) => {
            if (!crashed && invocations.length > 0) {
                crashed = true
                return Promise.reject(crashAfterDivert)
            }
            return recordProcessed(invocations)
        }
        expect(await crashLoop(quarantine, 1, crashOnce)).toEqual([crashAfterDivert])
        await startWorker(quarantine)
        await waitForExpect(() => expect(processed).toEqual([healthy]), 30_000)

        // Two flags on offset 0 mean the crash replayed the fetch that diverted the poison.
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(2)
        expect(await divertedWithKey(poison.key)).toHaveLength(1)
        expect(await counter('cdp_batch_diverted_messages_total', { group })).toEqual(1)
    })

    it('keeps crashing on the batch in shadow mode and diverts nothing', async () => {
        const quarantine = quarantineFor('shadow')
        await produce(poison)

        const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1)

        expect(crashes).toEqual(Array(MAX_ATTEMPTS + 1).fill(expect.any(SyntaxError)))
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'shadow' })).toEqual(1)
        expect(await divertedWithKey(poison.key)).toEqual([])
    })

    it('does not divert a batch that only failed while a dependency was down', async () => {
        const quarantine = quarantineFor('enforce')
        const id = await produceInvocation()
        let dependencyDown = true
        const consumeBatch: ConsumeBatch = (invocations) => {
            if (dependencyDown && invocations.length > 0) {
                return Promise.reject(
                    new DependencyUnavailableError('personhog unavailable', 'personhog', new Error('ECONNREFUSED'))
                )
            }
            return recordProcessed(invocations)
        }

        const crashes = await crashLoop(quarantine, MAX_ATTEMPTS + 1, consumeBatch)
        expect(crashes).toEqual(Array(MAX_ATTEMPTS + 1).fill(expect.any(DependencyUnavailableError)))
        expect(Number(await storedAttempts(quarantine, 0, 0))).toBeLessThanOrEqual(MAX_ATTEMPTS)

        dependencyDown = false
        await startWorker(quarantine, consumeBatch)

        await waitForExpect(() => expect(processed).toEqual([id]), 30_000)
        expect(await divertedWithKey(id)).toEqual([])
        expect(await counter('cdp_batch_diverted_total', { group, mode: 'enforce' })).toEqual(0)
    })
})
