import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'

import { KAFKA_CDP_QUARANTINE } from '~/common/config/kafka-topics'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createKafkaTestTopicName, deleteKafkaTopics, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { createExampleInvocation, insertHogFunction } from './_tests/fixtures'
import { CdpCyclotronWorker } from './consumers/cdp-cyclotron-worker.consumer'
import { CyclotronJobQueueKafka } from './services/job-queue/job-queue-kafka'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

const HOG_JOB_TOPIC = 'cdp_cyclotron_hog'

describe('CDP poison quarantine', () => {
    jest.setTimeout(60000)

    let hub: Hub
    let team: Team
    let kafkaProducer: KafkaProducerWrapper
    let cyclotronWorker: CdpCyclotronWorker | undefined
    let quarantineTopic: string

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args) => ActualKafkaProducerWrapper.create(...args))
        quarantineTopic = createKafkaTestTopicName(KAFKA_CDP_QUARANTINE)
        await ensureKafkaTopics([quarantineTopic, HOG_JOB_TOPIC])
        await resetTestDatabase()

        hub = await createHub()
        hub.CDP_POISON_QUARANTINE_ENABLED = true
        hub.CDP_QUARANTINE_TOPIC = quarantineTopic
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        team = await getFirstTeam(hub.postgres)
    })

    afterEach(async () => {
        await cyclotronWorker?.stop()
        cyclotronWorker = undefined
        await kafkaProducer.disconnect()
        await closeHub(hub)
        await deleteKafkaTopics([quarantineTopic])
    })

    const readQuarantined = async (expected: number): Promise<Message[]> => {
        const consumer = new KafkaConsumer(
            {
                topic: quarantineTopic,
                groupId: `e2e-read-${quarantineTopic}`,
                autoCommit: false,
                autoOffsetStore: false,
            },
            { 'auto.offset.reset': 'earliest' } as never
        )
        const messages: Message[] = []
        await consumer.connect((batch) => {
            messages.push(...batch)
            return Promise.resolve()
        })
        await waitForExpect(() => expect(messages.length).toBeGreaterThanOrEqual(expected), 30000)
        await consumer.disconnect()
        return messages
    }

    it('quarantines a hog job that cannot be read, and runs the job queued behind it', async () => {
        const fn = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })
        const neighbourUrl = `https://example.com/poison-neighbour-${randomUUID()}`
        const poison = Buffer.from(`{"not": "a hog job ${randomUUID()}"`)

        await kafkaProducer.produce({ topic: HOG_JOB_TOPIC, partition: 0, value: poison, key: null })
        await kafkaProducer.flush()

        const kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
        cyclotronWorker = new CdpCyclotronWorker(hub, createCdpConsumerDeps(hub, kafkaProducer), kafkaQueue)
        await cyclotronWorker.start()

        const quarantined = (await readQuarantined(1)).filter((message) => message.value?.equals(poison))
        expect(quarantined).toHaveLength(1)

        await kafkaQueue.queueInvocations([
            createExampleInvocation(fn, {
                project: { id: team.id } as any,
                inputs: { url: neighbourUrl, method: 'POST', body: { ok: true }, headers: {} },
            }),
        ])
        await waitForExpect(() => {
            expect(mockFetch.mock.calls.map(([url]) => url)).toContain(neighbourUrl)
        }, 30000)
    })
})
