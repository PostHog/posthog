import { Message } from 'node-rdkafka'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_CDP_QUARANTINE } from '~/common/config/kafka-topics'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { buildTestCdpProducerRegistry } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'

import { createCdpOutputsRegistry } from '../../outputs/registry'
import { EachBatchHandler, PoisonQuarantine } from './poison-quarantine'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

describe('PoisonQuarantine', () => {
    jest.setTimeout(60000)

    let kafkaProducer: KafkaProducerWrapper
    let quarantineTopic: string
    let quarantine: PoisonQuarantine

    beforeEach(async () => {
        quarantineTopic = createKafkaTestTopicName(KAFKA_CDP_QUARANTINE)
        await ensureKafkaTopics([quarantineTopic])
        kafkaProducer = await ActualKafkaProducerWrapper.create(defaultConfig.KAFKA_CLIENT_RACK)
        const config = { ...defaultConfig, CDP_POISON_QUARANTINE_ENABLED: true, CDP_QUARANTINE_TOPIC: quarantineTopic }
        quarantine = new PoisonQuarantine(
            config,
            createCdpOutputsRegistry().build(buildTestCdpProducerRegistry(kafkaProducer), config)
        )
    })

    afterEach(async () => {
        await kafkaProducer.disconnect()
        await deleteKafkaTopics([quarantineTopic])
    })

    const record = (name: string, offset: number): Message => ({
        topic: 'source',
        partition: 0,
        offset,
        value: Buffer.from(name),
        size: name.length,
    })

    const readQuarantinedValues = async (expected: number): Promise<string[]> => {
        const consumer = new KafkaConsumer(
            { topic: quarantineTopic, groupId: `read-${quarantineTopic}`, autoCommit: false, autoOffsetStore: false },
            { 'auto.offset.reset': 'earliest' } as never
        )
        const values: string[] = []
        await consumer.connect((batch) => {
            values.push(...batch.map((message) => message.value!.toString()))
            return Promise.resolve()
        })
        await waitForExpect(() => expect(values.length).toBeGreaterThanOrEqual(expected), 30000)
        await consumer.disconnect()
        return values
    }

    const wrap = (handler: EachBatchHandler): EachBatchHandler =>
        quarantine.wrap(handler, { consumerGroup: 'test-group', mayHaveSideEffects: false })

    it('runs a record that fails alone once, and quarantines only the one that fails alone twice', async () => {
        const processed: string[] = []
        let flakyFailures = 0
        const handler = wrap((messages) => {
            const names = messages.map((message) => message.value!.toString())
            if (names.includes('poison')) {
                return Promise.reject(new Error('poison'))
            }
            if (names.length === 1 && names[0] === 'flaky' && flakyFailures++ === 0) {
                return Promise.reject(new Error('flaky'))
            }
            processed.push(...names)
            return Promise.resolve()
        })

        await handler([record('flaky', 0), record('poison', 1), record('healthy', 2)])

        expect(processed.sort()).toEqual(['flaky', 'healthy'])
        expect(await readQuarantinedValues(1)).toEqual(['poison'])
    })

    const failNamed =
        (...prefixes: string[]): EachBatchHandler =>
        (messages) =>
            messages.some((message) => prefixes.some((prefix) => message.value!.toString().startsWith(prefix)))
                ? Promise.reject(new Error('dependency down'))
                : Promise.resolve()

    it.each([
        [
            'three in a batch of four',
            ['poison-0', 'poison-1', 'poison-2', 'healthy'],
            ['poison-0', 'poison-1', 'poison-2'],
        ],
        ['one alone in its batch', ['poison-0'], ['poison-0']],
    ])('quarantines records that fail alone: %s', async (_, names, expected) => {
        const handler = wrap(failNamed('poison'))

        await handler(names.map((name, offset) => record(name, offset)))

        expect((await readQuarantinedValues(expected.length)).sort()).toEqual(expected)
    })

    it('fails the batch and quarantines nothing when more records fail alone than poison would explain', async () => {
        const handler = wrap(failNamed('outage', 'poison'))
        const batch = [
            ...Array.from({ length: 4 }, (_, offset) => record(`outage-${offset}`, offset)),
            record('healthy', 4),
        ]

        await expect(handler(batch)).rejects.toThrow('dependency down')

        await handler([record('poison', 99), record('healthy', 100)])
        expect(await readQuarantinedValues(1)).toEqual(['poison'])
    })

    it.each([
        ['the whole batch', true],
        ['a record that fails alone', false],
    ])('fails the batch and quarantines nothing when %s fails with a retriable error', async (_, outageInBatch) => {
        const delivered: string[] = []
        const outage = Object.assign(new Error('lookup failed'), { isRetriable: true })
        const handler = wrap((messages) => {
            const names = messages.map((message) => message.value!.toString())
            if (names.includes('uncached')) {
                return Promise.reject(outageInBatch || names.length === 1 ? outage : new Error('batch failed'))
            }
            delivered.push(...names)
            return Promise.resolve()
        })

        await expect(handler([record('uncached', 0), record('cached', 1)])).rejects.toThrow(
            outageInBatch ? 'lookup failed' : 'batch failed'
        )
        expect(delivered).toEqual(outageInBatch ? [] : ['cached'])

        await wrap(failNamed('poison'))([record('poison', 99), record('healthy', 100)])
        expect(await readQuarantinedValues(1)).toEqual(['poison'])
    })

    it('runs every record of a failed batch alone at the same time', async () => {
        const size = 12
        let started = 0
        let releaseAll!: () => void
        const allStarted = new Promise<void>((resolve) => (releaseAll = resolve))
        const handler = wrap(async (messages) => {
            if (messages.length > 1) {
                throw new Error('batch failed')
            }
            if (++started === size) {
                releaseAll()
            }
            await allStarted
            if (messages[0].value!.toString() === 'poison') {
                throw new Error('poison')
            }
        })
        const batch = [
            record('poison', 0),
            ...Array.from({ length: size - 1 }, (_, offset) => record(`healthy-${offset}`, offset + 1)),
        ]

        await handler(batch)

        expect(await readQuarantinedValues(1)).toEqual(['poison'])
    })

    it('hands a background failure of a record that ran alone to the consumer, not the process', async () => {
        const unhandled: unknown[] = []
        const onUnhandled = (reason: unknown): number => unhandled.push(reason)
        process.on('unhandledRejection', onUnhandled)
        try {
            const handler = wrap(async (messages) => {
                if (messages.some((message) => message.value!.toString() === 'poison')) {
                    await new Promise((resolve) => setImmediate(resolve))
                    throw new Error('poison')
                }
                return { backgroundTask: Promise.reject(new Error('background failed')) }
            })

            const result = await handler([record('background', 0), record('poison', 1)])

            await expect(result?.backgroundTask).rejects.toThrow('background failed')
            expect(unhandled).toEqual([])
        } finally {
            process.off('unhandledRejection', onUnhandled)
        }
    })
})
