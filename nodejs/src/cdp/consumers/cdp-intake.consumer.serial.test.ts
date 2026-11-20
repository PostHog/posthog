import '~/tests/helpers/mocks/consumer.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { Pool } from 'pg'

import { createKafkaMessage } from '~/cdp/_tests/fixtures'
import { encodeIntakeMessage } from '~/cdp/intake/message'
import { KAFKA_CDP_INTAKE_DLQ } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'

import { Hub } from '../../types'
import { CdpIntakeConsumer } from './cdp-intake.consumer'

describe('CdpIntakeConsumer', () => {
    let hub: Hub
    let pool: Pool
    let consumer: CdpIntakeConsumer

    const sendMessage = (id: string): Buffer => {
        const encoded = encodeIntakeMessage({
            kind: 'transactional-email',
            fingerprint: 'fingerprint-a',
            job: {
                id,
                teamId: 7,
                functionId: '0193a7b2-0000-7000-8000-000000000001',
                queueName: 'email',
                priority: 0,
                scheduled: new Date(),
                state: Buffer.from(JSON.stringify({ state: { actionStepCount: 0 } })),
            },
        })
        if (encoded.status !== 'encoded') {
            throw new Error('expected an encoded message')
        }
        return encoded.message.value
    }

    beforeEach(async () => {
        hub = await createHub({ CDP_DLQ_ENABLED: true })
        pool = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
        mockProducerObserver.resetKafkaProducer()
        consumer = new CdpIntakeConsumer(hub, createCdpConsumerDeps(hub), 'transactional-email')
    })

    afterEach(async () => {
        await consumer.stop()
        await pool.end()
        await closeHub(hub)
    })

    it('queues a run as a cyclotron job and parks a message that can never insert on the intake dead-letter topic', async () => {
        const id = new UUIDT().toString()
        const invalid = { v: 1, kind: 'transactional-email' }

        await consumer.processBatch([
            createKafkaMessage(parseJSON(sendMessage(id).toString()), { offset: 1 }),
            createKafkaMessage(invalid, { offset: 2 }),
        ])

        const jobs = await pool.query('SELECT id FROM cyclotron_jobs WHERE id = $1', [id])
        expect(jobs.rows).toEqual([{ id }])
        expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_CDP_INTAKE_DLQ)).toEqual([
            expect.objectContaining({
                value: invalid,
                headers: expect.objectContaining({
                    dlq_reason: 'schema_invalid',
                    dlq_consumer_group: 'cdp-intake-transactional-email-consumer',
                }),
            }),
        ])
    })
})
