import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'

import { defaultConfig } from '../../src/config/config'
import { UUIDT } from '../../src/utils/utils'
import { capture, createOrganization, createTeam } from '../api'
import { waitForExpect } from '../expectations'

let kafka: Kafka
let organizationId: string

let warningMessages: KafkaMessage[]
let warningConsumer: Consumer

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })

    // Make sure the ingest warnings topic exists before starting the consumer
    const admin = kafka.admin()
    const topic = 'clickhouse_ingestion_warnings' // note: functional tests don't use _test suffix as in config
    await admin.createTopics({ topics: [{ topic: topic }] })
    await admin.disconnect()

    warningMessages = []
    warningConsumer = kafka.consumer({ groupId: 'events_plugin_ingestion_test' })
    await warningConsumer.subscribe({ topic: topic, fromBeginning: true })
    await warningConsumer.run({
        eachMessage: ({ message }) => {
            warningMessages.push(message)
            return Promise.resolve()
        },
    })

    organizationId = await createOrganization()
})

afterAll(async () => {
    await warningConsumer.disconnect()
})

test.concurrent('consumer produces ingest warnings for messages over 1MB', async () => {
    // For this we basically want the plugin-server to try and produce a new
    // message larger than 1MB. We do this by creating a person with a lot of
    // properties. We will end up denormalizing the person properties onto the
    // event, which already has the properties as $set therefore resulting in a
    // message that's larger than 1MB. There may also be other attributes that
    // are added to the event which pushes it over the limit.
    //
    // We verify that this is handled by checking that there is a message in the
    // appropriate topic.
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

    // Verify we have a message corresponding to the input event.
    await waitForExpect(() => {
        const [message] = warningMessages.filter((message: KafkaMessage) => {
            if (message.value) {
                const payload = JSON.parse(message.value.toString())
                const details = JSON.parse(payload.details)
                return details.eventUuid === personEventUuid && details.distinctId === distinctId
            }
        })
        expect(message).toBeDefined()
        return message
    })
})
