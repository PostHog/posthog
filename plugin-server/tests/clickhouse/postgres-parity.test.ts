import { DateTime } from 'luxon'
import { PoolClient } from 'pg'

import { startPluginsServer } from '../../src/main/pluginsServer'
import {
    Database,
    Hub,
    LogLevel,
    PluginsServerConfig,
    PropertyUpdateOperation,
    Team,
    TimestampFormat,
} from '../../src/types'
import { castTimestampOrNow, delay, UUIDT } from '../../src/utils/utils'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetKafka } from '../helpers/kafka'
import { pluginConfig39 } from '../helpers/plugins'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

jest.mock('../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    KAFKA_ENABLED: true,
    KAFKA_HOSTS: process.env.KAFKA_HOSTS || 'kafka:9092',
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
}

describe('postgres parity', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let team: Team

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)
        await resetTestDatabaseClickhouse(extraServerConfig)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        stopServer = startResponse.stop
        posthog = createPosthog(hub, pluginConfig39)
        team = await getFirstTeam(hub)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('createPerson', async () => {
        const uuid = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userPropOnce: 'propOnceValue' },
            team.id,
            null,
            true,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse))
        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(person, Database.ClickHouse), 2)

        const clickHousePersons = await hub.db.fetchPersons(Database.ClickHouse)
        expect(clickHousePersons).toEqual([
            {
                id: uuid,
                created_at: expect.any(String), // '2021-02-04 00:18:26.472',
                team_id: team.id,
                properties: '{"userPropOnce":"propOnceValue","userProp":"propValue"}',
                is_identified: 1,
                is_deleted: 0,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
            },
        ])
        const clickHouseDistinctIds = await hub.db.fetchDistinctIdValues(person, Database.ClickHouse)
        expect(clickHouseDistinctIds).toEqual(['distinct1', 'distinct2'])

        const postgresPersons = await hub.db.fetchPersons(Database.Postgres)
        expect(postgresPersons).toEqual([
            {
                id: expect.any(Number),
                created_at: expect.any(DateTime),
                properties: {
                    userProp: 'propValue',
                    userPropOnce: 'propOnceValue',
                },
                properties_last_updated_at: {
                    userProp: expect.any(String),
                    userPropOnce: expect.any(String),
                },
                properties_last_operation: {
                    userProp: PropertyUpdateOperation.Set,
                    userPropOnce: PropertyUpdateOperation.SetOnce,
                },
                team_id: 2,
                is_user_id: null,
                is_identified: true,
                uuid: uuid,
                version: 0,
            },
        ])
        const postgresDistinctIds = await hub.db.fetchDistinctIdValues(person, Database.Postgres)
        expect(postgresDistinctIds).toEqual(['distinct1', 'distinct2'])

        expect(person).toEqual(postgresPersons[0])
    })

    test('updatePerson', async () => {
        const uuid = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            {},
            team.id,
            null,
            false,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse))
        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(person, Database.ClickHouse), 2)

        // update properties and set is_identified to true
        await hub.db.updatePerson(person, { properties: { replacedUserProp: 'propValue' }, is_identified: true })

        await delayUntilEventIngested(async () =>
            (await hub.db.fetchPersons(Database.ClickHouse)).filter((p) => p.is_identified)
        )

        const clickHousePersons = await hub.db.fetchPersons(Database.ClickHouse)
        const postgresPersons = await hub.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons.length).toEqual(1)
        expect(postgresPersons.length).toEqual(1)

        expect(postgresPersons[0].is_identified).toEqual(true)
        expect(postgresPersons[0].version).toEqual(1)
        expect(postgresPersons[0].properties).toEqual({ replacedUserProp: 'propValue' })

        expect(clickHousePersons[0].is_identified).toEqual(1)
        expect(clickHousePersons[0].is_deleted).toEqual(0)
        expect(clickHousePersons[0].properties).toEqual('{"replacedUserProp":"propValue"}')

        // update date and boolean to false

        const randomDate = DateTime.utc().minus(100000).setZone('UTC')
        const updatedPerson = await hub.db.updatePerson(person, { created_at: randomDate, is_identified: false })

        expect(updatedPerson.version).toEqual(2)

        await delayUntilEventIngested(async () =>
            (await hub.db.fetchPersons(Database.ClickHouse)).filter((p) => !p.is_identified)
        )

        const clickHousePersons2 = await hub.db.fetchPersons(Database.ClickHouse)
        const postgresPersons2 = await hub.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons2.length).toEqual(1)
        expect(postgresPersons2.length).toEqual(1)

        expect(postgresPersons2[0].is_identified).toEqual(false)
        expect(postgresPersons2[0].created_at.toISO()).toEqual(randomDate.toISO())

        expect(clickHousePersons2[0].is_identified).toEqual(0)
        expect(clickHousePersons2[0].created_at).toEqual(
            // TODO: get rid of `+ '.000'` by removing the need for ClickHouseSecondPrecision on CH persons
            castTimestampOrNow(randomDate, TimestampFormat.ClickHouseSecondPrecision) + '.000'
        )
    })

    test('addDistinctId', async () => {
        const uuid = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            {},
            team.id,
            null,
            true,
            uuid,
            ['distinct1']
        )
        const anotherPerson = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            {},
            team.id,
            null,
            true,
            uuid2,
            ['another_distinct_id']
        )
        await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse))
        const [postgresPerson] = await hub.db.fetchPersons(Database.Postgres)

        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse), 1)
        const clickHouseDistinctIdValues = await hub.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse)
        const postgresDistinctIdValues = await hub.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        // check that all is in the right format

        expect(clickHouseDistinctIdValues).toEqual(['distinct1'])
        expect(postgresDistinctIdValues).toEqual(['distinct1'])

        const clickHouseDistinctIds = await hub.db.fetchDistinctIds(postgresPerson, Database.ClickHouse)
        const postgresDistinctIds = await hub.db.fetchDistinctIds(postgresPerson, Database.Postgres)

        expect(clickHouseDistinctIds).toEqual([
            {
                distinct_id: 'distinct1',
                person_id: person.uuid,
                team_id: team.id,
                _sign: 1,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
            },
        ])
        expect(postgresDistinctIds).toEqual([
            expect.objectContaining({
                distinct_id: 'distinct1',
                person_id: person.id,
                team_id: team.id,
            }),
        ])

        // add 'anotherOne' to person

        await hub.db.addDistinctId(postgresPerson, 'anotherOne')

        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse), 2)

        const clickHouseDistinctIdValues2 = await hub.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse)
        const postgresDistinctIdValues2 = await hub.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        expect(clickHouseDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])
        expect(postgresDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])

        // check anotherPerson for their initial distinct id

        const clickHouseDistinctIdValuesOther = await hub.db.fetchDistinctIdValues(anotherPerson, Database.ClickHouse)
        const postgresDistinctIdValuesOther = await hub.db.fetchDistinctIdValues(anotherPerson, Database.Postgres)

        expect(clickHouseDistinctIdValuesOther).toEqual(['another_distinct_id'])
        expect(postgresDistinctIdValuesOther).toEqual(['another_distinct_id'])
    })

    test('moveDistinctIds & deletePerson', async () => {
        const uuid = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            {},
            team.id,
            null,
            false,
            uuid,
            ['distinct1']
        )
        const anotherPerson = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            {},
            team.id,
            null,
            true,
            uuid2,
            ['another_distinct_id']
        )
        await delayUntilEventIngested(() => hub.db.fetchPersons(Database.ClickHouse))
        const [postgresPerson] = await hub.db.fetchPersons(Database.Postgres)

        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(postgresPerson, Database.ClickHouse), 1)

        // move distinct ids from person to to anotherPerson

        const kafkaMessages = await hub.db.moveDistinctIds(person, anotherPerson)
        for (const kafkaMessage of kafkaMessages) {
            await hub.db!.kafkaProducer!.queueMessage(kafkaMessage)
        }
        await delayUntilEventIngested(() => hub.db.fetchDistinctIdValues(anotherPerson, Database.ClickHouse), 2)

        // it got added

        const clickHouseDistinctIdValuesMoved = await hub.db.fetchDistinctIdValues(anotherPerson, Database.ClickHouse)
        const postgresDistinctIdValuesMoved = await hub.db.fetchDistinctIdValues(anotherPerson, Database.Postgres)

        expect(clickHouseDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))
        expect(postgresDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))

        // it got removed

        const clickHouseDistinctIdValuesRemoved = await hub.db.fetchDistinctIdValues(
            postgresPerson,
            Database.ClickHouse
        )
        const postgresDistinctIdValuesRemoved = await hub.db.fetchDistinctIdValues(postgresPerson, Database.Postgres)

        expect(clickHouseDistinctIdValuesRemoved).toEqual([])
        expect(postgresDistinctIdValuesRemoved).toEqual([])

        // delete person

        await hub.db.postgresTransaction(async (client) => {
            const deletePersonMessage = await hub.db.deletePerson(person, client)
            await hub.db!.kafkaProducer!.queueMessage(deletePersonMessage[0])
        })

        // Check distinct ids
        await delayUntilEventIngested(async () =>
            (await hub.db.fetchPersons(Database.ClickHouse)).length === 1 ? ['deleted!'] : []
        )
        await delayUntilEventIngested(async () =>
            (await hub.db.fetchDistinctIdValues(person, Database.ClickHouse)).length === 1 ? ['deleted!'] : []
        )

        const clickHousePersons = await hub.db.fetchPersons(Database.ClickHouse)
        const postgresPersons = await hub.db.fetchPersons(Database.Postgres)

        expect(clickHousePersons.length).toEqual(1)
        expect(postgresPersons.length).toEqual(1)
    })
})
