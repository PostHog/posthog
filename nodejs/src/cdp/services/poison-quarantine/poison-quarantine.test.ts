import { Message } from 'node-rdkafka'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_CDP_QUARANTINE } from '~/common/config/kafka-topics'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { buildTestCdpProducerRegistry } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'

import { createCdpOutputsRegistry } from '../../outputs/registry'
import { EachBatchHandler, MAX_QUARANTINED_PER_BATCH, PoisonQuarantine } from './poison-quarantine'

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

    it('fails the batch and quarantines nothing when more records fail alone than poison would explain', async () => {
        const alwaysFails = wrap(() => Promise.reject(new Error('dependency down')))
        const outage = Array.from({ length: MAX_QUARANTINED_PER_BATCH + 1 }, (_, offset) =>
            record(`outage-${offset}`, offset)
        )

        await expect(alwaysFails(outage)).rejects.toThrow('dependency down')

        await alwaysFails([record('lone', 99)])
        expect(await readQuarantinedValues(1)).toEqual(['lone'])
    })
})
