import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'

import { defaultConfig } from '../../src/config/config'
import { UUIDT } from '../../src/utils/utils'
import { capture, createOrganization, createTeam } from '../api'
import { waitForExpect } from '../expectations'

let kafka: Kafka
let organizationId: string

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })

    // Make sure the dlq topic exists before starting the consumer
    const admin = kafka.admin()
    await admin.createTopics({ topics: [{ topic: 'events_plugin_ingestion_dlq' }] })
    await admin.disconnect()

    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'events_plugin_ingestion_test' })
    await dlqConsumer.subscribe({ topic: 'events_plugin_ingestion_dlq', fromBeginning: true })
    await dlqConsumer.run({
        eachMessage: ({ message }) => {
            dlq.push(message)
            return Promise.resolve()
        },
    })

    organizationId = await createOrganization()
})

afterAll(async () => {
    await dlqConsumer.disconnect()
})

test.concurrent('consumer handles messages just over 1MB gracefully', async () => {
    // For this we basically want the plugin-server to try and produce a new
    // message larger than 1MB. We do this by creating a person with a lot of
    // properties. We will end up denormalizing the person properties onto the
    // event, which already has the properties as $set therefore resulting in a
    // message that's larger than 1MB. There may also be other attributes that
    // are added to the event which pushes it over the limit.
    //
    // We verify that at least some error has happened by checking that there is
    // a message in the DLQ.
    const token = new UUIDT().toString()
    const teamId = await createTeam(organizationId, undefined, token)
    const distinctId = new UUIDT().toString()

    const personProperties = {
        distinct_id: distinctId,
        $set: {},
    }

    for (let i = 0; i < 10000; i++) {
        personProperties.$set[new UUIDT().toString()] = new UUIDT().toString()
    }

    const personEventUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: personEventUuid,
        event: '$identify',
        properties: personProperties,
    })

    // Verify we have a message in the DLQ, along a Sentry event id in the
    // header `sentry-event-id`.
    const message = await waitForExpect(() => {
        const [message] = dlq.filter((message) => message.headers?.['event-id']?.toString() === personEventUuid)
        expect(message).toBeDefined()
        return message
    })
    expect(message.headers?.['sentry-event-id']).toBeDefined()
})
