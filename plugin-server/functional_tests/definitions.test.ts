import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, getPropertyDefinitions } from './api'
import { waitForExpect } from './expectations'
// import { beforeAll, afterAll, test, expect } from 'vitest'

let producer: Producer
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let organizationId: string

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS] })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end()])
})

test.concurrent(`event ingestion: definition for string property %p`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = 'distinctId'
    const uuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, uuid, 'custom event', {
        property: 'hehe',
    })

    await waitForExpect(async () => {
        const propertyDefinitions = await getPropertyDefinitions(postgres, teamId)
        expect(propertyDefinitions).toContainEqual(
            expect.objectContaining({
                name: 'property',
                is_numerical: false,
                property_type: 'String',
            })
        )
    })
})

test.concurrent.each([[2], [2.1234], ['2'], ['2.1234']])(
    `event ingestion: definition for number property as number %p`,
    async (numberValue: any) => {
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture(producer, teamId, distinctId, uuid, 'custom event', {
            property: numberValue,
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(postgres, teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: 'property',
                    is_numerical: true,
                    property_type: 'Numeric',
                })
            )
        })
    }
)

test.concurrent.each([
    ['01/01/2020 00:00:00'],
    ['01-01-2020 00:00:00'],
    ['2020/01/01 00:00:00'],
    ['2020-01-01T00:00:00Z'],
    ['2020-01-01 00:00:00'],
    ['2020-01-01'],
])(`event ingestion: definition for date/datetime property should be datetime %p`, async (dateString: string) => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = 'distinctId'
    const uuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, uuid, 'custom event', {
        property: dateString,
    })

    await waitForExpect(async () => {
        const propertyDefinitions = await getPropertyDefinitions(postgres, teamId)
        expect(propertyDefinitions).toContainEqual(
            expect.objectContaining({
                name: 'property',
                is_numerical: false,
                property_type: 'DateTime',
            })
        )
    })
})

test.concurrent.each([[true], ['true']])(
    `event ingestion: definition for boolean property %p`,
    async (booleanValue: any) => {
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture(producer, teamId, distinctId, uuid, 'custom event', {
            property: booleanValue,
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(postgres, teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: 'property',
                    is_numerical: false,
                    property_type: 'Boolean',
                })
            )
        })
    }
)

test.concurrent.each([['utm_abc'], ['utm_123']])(
    `event ingestion: utm properties should always be strings`,
    async (propertyName: string) => {
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = 'distinctId'
        const uuid = new UUIDT().toString()

        await capture(producer, teamId, distinctId, uuid, 'custom event', {
            [propertyName]: 1234,
        })

        await waitForExpect(async () => {
            const propertyDefinitions = await getPropertyDefinitions(postgres, teamId)
            expect(propertyDefinitions).toContainEqual(
                expect.objectContaining({
                    name: propertyName,
                    is_numerical: false,
                    property_type: 'String',
                })
            )
        })
    }
)
