import '~/tests/helpers/mocks/consumer.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { Message } from 'node-rdkafka'
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

    const sendMessage = (id: string, shadow?: boolean): Buffer => {
        const encoded = encodeIntakeMessage({
            kind: 'transactional-email',
            fingerprint: 'fingerprint-a',
            shadow,
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

    const dlq = (value: Buffer, group: string, offset: number): Message => ({
        ...createKafkaMessage(parseJSON(value.toString()), { offset, topic: KAFKA_CDP_INTAKE_DLQ }),
        headers: [{ dlq_consumer_group: group }],
    })
    const ownGroup = 'cdp-intake-transactional-email-consumer'
    const stillInvalid = Buffer.from(JSON.stringify({ v: 1, kind: 'transactional-email' }))

    it("drains its own dead letters, but not another group's or a shadow copy the route inserted, even one that fails to decode", async () => {
        const [own, other, shadow] = [new UUIDT().toString(), new UUIDT().toString(), new UUIDT().toString()]

        await consumer.drainBatch([
            dlq(sendMessage(own), ownGroup, 1),
            dlq(sendMessage(other), 'cdp-intake-workflow-webhook-consumer', 2),
            dlq(sendMessage(shadow, true), ownGroup, 3),
            dlq(Buffer.from(JSON.stringify({ v: 1, kind: 'transactional-email', shadow: true })), ownGroup, 4),
        ])

        const jobs = await pool.query('SELECT id FROM cyclotron_jobs WHERE id = ANY($1)', [[own, other, shadow]])
        expect(jobs.rows).toEqual([{ id: own }])
    })

    it('holds a drain batch with a record that still fails, inserting none of it and parking nothing', async () => {
        const id = new UUIDT().toString()

        await expect(
            consumer.drainBatch([dlq(sendMessage(id), ownGroup, 1), dlq(stillInvalid, ownGroup, 2)])
        ).rejects.toThrow('still fails: schema_invalid')

        const jobs = await pool.query('SELECT id FROM cyclotron_jobs WHERE id = $1', [id])
        expect(jobs.rows).toEqual([])
        expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_CDP_INTAKE_DLQ)).toEqual([])
    })
})
