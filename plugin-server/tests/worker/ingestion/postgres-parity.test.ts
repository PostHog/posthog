import { DateTime } from 'luxon'

import { PluginServer } from '../../../src/server'
import {
    Hub,
    LogLevel,
    PluginServerMode,
    PluginsServerConfig,
    PropertyUpdateOperation,
    TimestampFormat,
} from '../../../src/types'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { parseJSON } from '../../../src/utils/json-parse'
import { castTimestampOrNow, UUIDT } from '../../../src/utils/utils'
import { Clickhouse } from '../../helpers/clickhouse'
import { resetKafka } from '../../helpers/kafka'
import { createUserTeamAndOrganization, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/logger')
jest.setTimeout(30000)

const extraServerConfig: Partial<PluginsServerConfig> = {
    LOG_LEVEL: LogLevel.Info,
}

describe('postgres parity', () => {
    jest.retryTimes(5) // Flakey due to reliance on kafka/clickhouse
    let hub: Hub
    let server: PluginServer
    let teamId = 10 // Incremented every test. Avoids late ingestion causing issues
    let clickhouse: Clickhouse

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)

        clickhouse = Clickhouse.create()
        await clickhouse.resetTestDatabase()
        server = new PluginServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()
        hub = server.hub!
        teamId++
        await createUserTeamAndOrganization(
            hub.db.postgres,
            teamId,
            teamId,
            new UUIDT().toString(),
            new UUIDT().toString(),
            new UUIDT().toString()
        )
    })

    afterEach(async () => {
        clickhouse.close()
        await server.stop()
    })

    test('createPerson', async () => {
        const uuid = new UUIDT().toString()
        const ts = DateTime.now().toString()
        const [person, kafkaMessages] = await hub.db.createPerson(
            DateTime.utc(),
            { userPropOnce: 'propOnceValue', userProp: 'propValue' },
            { userProp: ts, userPropOnce: ts },
            { userProp: PropertyUpdateOperation.Set, userPropOnce: PropertyUpdateOperation.SetOnce },
            teamId,
            null,
            true,
            uuid,
            [{ distinctId: 'distinct1' }, { distinctId: 'distinct2' }]
        )
        await hub.db.kafkaProducer.queueMessages(kafkaMessages)

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchPersons())
        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIdValues(person), 2)
        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIds(person), 2)

        const clickHousePersons = (await clickhouse.fetchPersons()).map((row) => ({
            ...row,
            properties: parseJSON(row.properties), // avoids depending on key sort order
        }))
        expect(clickHousePersons).toMatchObject([
            {
                id: uuid,
                created_at: expect.any(String), // '2021-02-04 00:18:26.472',
                team_id: teamId.toString(),
                properties: { userPropOnce: 'propOnceValue', userProp: 'propValue' },
                is_identified: 1,
                is_deleted: 0,
            },
        ])
        const clickHouseDistinctIds = await clickhouse.fetchDistinctIdValues(person)
        expect(clickHouseDistinctIds).toEqual(['distinct1', 'distinct2'])

        const postgresPersons = await hub.db.fetchPersons()
        expect(postgresPersons).toEqual([
            {
                id: expect.any(String),
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
                team_id: teamId,
                is_user_id: null,
                is_identified: true,
                uuid: uuid,
                version: 0,
            },
        ])
        const postgresDistinctIds = await hub.db.fetchDistinctIdValues(person)
        expect(postgresDistinctIds).toEqual(['distinct1', 'distinct2'])

        const newClickHouseDistinctIdValues = await clickhouse.fetchDistinctIds(person)
        expect(newClickHouseDistinctIdValues).toMatchObject([
            {
                distinct_id: 'distinct1',
                person_id: person.uuid,
                team_id: teamId.toString(),
                version: '0',
                is_deleted: 0,
            },
            {
                distinct_id: 'distinct2',
                person_id: person.uuid,
                team_id: teamId.toString(),
                version: '0',
                is_deleted: 0,
            },
        ])

        expect(person).toEqual(postgresPersons[0])
    })

    test('updatePerson', async () => {
        const uuid = new UUIDT().toString()
        const [person, kafkaMessages] = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            false,
            uuid,
            [{ distinctId: 'distinct1' }, { distinctId: 'distinct2' }]
        )
        await hub.db.kafkaProducer.queueMessages(kafkaMessages)

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchPersons())
        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIdValues(person), 2)

        // update properties and set is_identified to true
        const [_p, kafkaMessagesUpdate] = await hub.db.updatePerson(person, {
            properties: { replacedUserProp: 'propValue' },
            is_identified: true,
        })
        await hub.db.kafkaProducer.queueMessages(kafkaMessagesUpdate)

        await clickhouse.delayUntilEventIngested(async () =>
            (await clickhouse.fetchPersons()).filter((p) => p.is_identified)
        )

        const clickHousePersons = await clickhouse.fetchPersons()
        const postgresPersons = await hub.db.fetchPersons()

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
        const [updatedPerson, kafkaMessages2] = await hub.db.updatePerson(person, {
            created_at: randomDate,
            is_identified: false,
        })

        await hub.db.kafkaProducer.queueMessages(kafkaMessages2)

        expect(updatedPerson.version).toEqual(2)

        await clickhouse.delayUntilEventIngested(async () =>
            (await clickhouse.fetchPersons()).filter((p) => !p.is_identified)
        )

        const clickHousePersons2 = await clickhouse.fetchPersons()
        const postgresPersons2 = await hub.db.fetchPersons()

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
        const [person, personKafkaMessages] = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid,
            [{ distinctId: 'distinct1' }]
        )
        await hub.db.kafkaProducer.queueMessages(personKafkaMessages)

        const [anotherPerson, anotherPersonKafkaMessages] = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid2,
            [{ distinctId: 'another_distinct_id' }]
        )
        await hub.db.kafkaProducer.queueMessages(anotherPersonKafkaMessages)

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchPersons())
        const [postgresPerson] = await hub.db.fetchPersons()

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIds(postgresPerson), 1)
        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIds(postgresPerson), 1)
        const clickHouseDistinctIdValues = await clickhouse.fetchDistinctIdValues(postgresPerson)
        const postgresDistinctIdValues = await hub.db.fetchDistinctIdValues(postgresPerson)

        // check that all is in the right format

        expect(clickHouseDistinctIdValues).toEqual(['distinct1'])
        expect(postgresDistinctIdValues).toEqual(['distinct1'])

        const postgresDistinctIds = await hub.db.fetchDistinctIds(postgresPerson)
        const newClickHouseDistinctIdValues = await clickhouse.fetchDistinctIds(postgresPerson)

        expect(postgresDistinctIds).toEqual([
            expect.objectContaining({
                distinct_id: 'distinct1',
                person_id: person.id,
                team_id: teamId,
                version: '0',
            }),
        ])
        expect(newClickHouseDistinctIdValues).toMatchObject([
            {
                distinct_id: 'distinct1',
                person_id: person.uuid,
                team_id: teamId.toString(),
                version: '0',
                is_deleted: 0,
            },
        ])

        // add 'anotherOne' to person

        const kafkaMessagesAddDistinctId = await hub.db.addDistinctId(postgresPerson, 'anotherOne', 0)
        await hub.db.kafkaProducer.queueMessages(kafkaMessagesAddDistinctId)

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIdValues(postgresPerson), 2)

        const clickHouseDistinctIdValues2 = await clickhouse.fetchDistinctIdValues(postgresPerson)
        const postgresDistinctIdValues2 = await hub.db.fetchDistinctIdValues(postgresPerson)

        expect(clickHouseDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])
        expect(postgresDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])

        // check anotherPerson for their initial distinct id

        const clickHouseDistinctIdValuesOther = await clickhouse.fetchDistinctIdValues(anotherPerson)
        const postgresDistinctIdValuesOther = await hub.db.fetchDistinctIdValues(anotherPerson)

        expect(clickHouseDistinctIdValuesOther).toEqual(['another_distinct_id'])
        expect(postgresDistinctIdValuesOther).toEqual(['another_distinct_id'])
    })

    test('moveDistinctIds & deletePerson', async () => {
        const uuid = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const [person, kafkaMessagesPerson] = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            false,
            uuid,
            [{ distinctId: 'distinct1' }]
        )
        await hub.db.kafkaProducer.queueMessages(kafkaMessagesPerson)

        const [anotherPerson, kafkaMessagesAnotherPerson] = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid2,
            [{ distinctId: 'another_distinct_id' }]
        )
        await hub.db.kafkaProducer.queueMessages(kafkaMessagesAnotherPerson)

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchPersons())
        const [postgresPerson] = await hub.db.fetchPersons()

        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIdValues(postgresPerson), 1)

        // move distinct ids from person to to anotherPerson

        const moveDistinctIdsResult = await hub.db.moveDistinctIds(person, anotherPerson)
        expect(moveDistinctIdsResult.success).toEqual(true)

        if (moveDistinctIdsResult.success) {
            await hub.db!.kafkaProducer!.queueMessages(moveDistinctIdsResult.messages)
        }
        await clickhouse.delayUntilEventIngested(() => clickhouse.fetchDistinctIdValues(anotherPerson), 2)

        // it got added

        // :TODO: Update version
        const clickHouseDistinctIdValuesMoved = await clickhouse.fetchDistinctIdValues(anotherPerson)
        const postgresDistinctIdValuesMoved = await hub.db.fetchDistinctIdValues(anotherPerson)
        const newClickHouseDistinctIdValues = await clickhouse.delayUntilEventIngested(
            () => clickhouse.fetchDistinctIds(anotherPerson),
            2
        )

        expect(postgresDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))
        expect(clickHouseDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))
        expect(newClickHouseDistinctIdValues).toMatchObject([
            {
                distinct_id: 'another_distinct_id',
                person_id: anotherPerson.uuid,
                team_id: teamId.toString(),
                version: '0',
                is_deleted: 0,
            },
            {
                distinct_id: 'distinct1',
                person_id: anotherPerson.uuid,
                team_id: teamId.toString(),
                version: '1',
                is_deleted: 0,
            },
        ])

        // it got removed

        const clickHouseDistinctIdValuesRemoved = await clickhouse.fetchDistinctIdValues(postgresPerson)
        const postgresDistinctIdValuesRemoved = await hub.db.fetchDistinctIdValues(postgresPerson)
        const newClickHouseDistinctIdRemoved = await clickhouse.fetchDistinctIds(postgresPerson)

        expect(clickHouseDistinctIdValuesRemoved).toEqual([])
        expect(postgresDistinctIdValuesRemoved).toEqual([])
        expect(newClickHouseDistinctIdRemoved).toEqual([])

        // delete person
        await hub.db.postgres.transaction(PostgresUse.PERSONS_WRITE, '', async (client) => {
            const deletePersonMessage = await hub.db.deletePerson(person, client)
            await hub.db!.kafkaProducer!.queueMessages(deletePersonMessage[0])
        })

        await clickhouse.delayUntilEventIngested(async () =>
            (await clickhouse.fetchPersons()).length === 1 ? ['deleted!'] : []
        )
        const clickHousePersons = await clickhouse.fetchPersons()
        const postgresPersons = await hub.db.fetchPersons()

        expect(clickHousePersons.length).toEqual(1)
        expect(postgresPersons.length).toEqual(1)
    })
})
