import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam } from './api'
import { waitForExpect } from './expectations'

let kafka: Kafka
let overflow: KafkaMessage[]
let overflowConsumer: Consumer

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })

    overflow = []
    overflowConsumer = kafka.consumer({ groupId: 'ingestion-overflow-test' })
    await overflowConsumer.subscribe({ topic: 'events_plugin_ingestion_overflow', fromBeginning: true })
    await overflowConsumer.run({
        eachMessage: ({ message }) => {
            overflow.push(message)
            return Promise.resolve()
        },
    })
})

afterAll(async () => {
    await overflowConsumer.disconnect()
})

test(`ensure that a large bursts of events is diverted to the overflow topic`, async () => {
    const organizationId = await createOrganization()
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    Array.from(new Array(10000).keys()).map((_) =>
        capture({ teamId, distinctId, uuid: new UUIDT().toString(), event: 'custom event' })
    )

    await waitForExpect(() => {
        expect(overflow.length).toBeGreaterThan(0)
    })
})
