import { DateTime } from 'luxon'

import { Database, Hub, PropertyUpdateOperation, TimestampFormat } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { castTimestampOrNow, UUIDT } from '../../../src/utils/utils'
import {
    delayUntilEventIngested,
    fetchClickHouseDistinctIdValues,
    fetchClickHousePersons,
    fetchDistinctIdsClickhouse,
} from '../../helpers/clickhouse'
import { fetchDistinctIds, fetchDistinctIdValues, fetchPostgresPersons } from '../../helpers/postgres'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.setTimeout(10000) // 60 sec timeout

describe('postgres parity', () => {
    let hub: Hub
    let closeHub: (() => Promise<void>) | undefined
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    beforeEach(async () => {
        ;({ teamId } = await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `))
    })

    afterAll(async () => {
        await closeHub?.()
    })

    test('createPerson', async () => {
        const uuid = new UUIDT().toString()
        const ts = DateTime.now().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userPropOnce: 'propOnceValue', userProp: 'propValue' },
            { userProp: ts, userPropOnce: ts },
            { userProp: PropertyUpdateOperation.Set, userPropOnce: PropertyUpdateOperation.SetOnce },
            teamId,
            null,
            true,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => fetchClickHousePersons(teamId))
        await delayUntilEventIngested(() => fetchClickHouseDistinctIdValues(teamId, person.uuid), 2)
        await delayUntilEventIngested(() => fetchDistinctIdsClickhouse(teamId, person.uuid), 2)

        const clickHousePersons = await fetchClickHousePersons(teamId)
        expect(clickHousePersons).toEqual([
            {
                id: uuid,
                created_at: expect.any(String), // '2021-02-04 00:18:26.472',
                team_id: teamId,
                properties: '{"userPropOnce":"propOnceValue","userProp":"propValue"}',
                is_identified: 1,
                is_deleted: 0,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
                version: 0,
            },
        ])
        const clickHouseDistinctIds = await fetchClickHouseDistinctIdValues(teamId, person.uuid)
        expect(clickHouseDistinctIds).toEqual(['distinct1', 'distinct2'])

        const postgresPersons = await fetchPostgresPersons(teamId)
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
                team_id: teamId,
                is_user_id: null,
                is_identified: true,
                uuid: uuid,
                version: 0,
            },
        ])
        const postgresDistinctIds = await fetchDistinctIdValues(person.id)
        expect(postgresDistinctIds).toEqual(['distinct1', 'distinct2'])

        const newClickHouseDistinctIdValues = await hub.db.fetchDistinctIds(person, Database.ClickHouse)
        expect(newClickHouseDistinctIdValues).toEqual(
            expect.arrayContaining([
                {
                    distinct_id: 'distinct1',
                    person_id: person.uuid,
                    team_id: teamId,
                    version: 0,
                    is_deleted: 0,
                    _timestamp: expect.any(String),
                    _offset: expect.any(Number),
                    _partition: expect.any(Number),
                },
                {
                    distinct_id: 'distinct2',
                    person_id: person.uuid,
                    team_id: teamId,
                    version: 0,
                    is_deleted: 0,
                    _timestamp: expect.any(String),
                    _offset: expect.any(Number),
                    _partition: expect.any(Number),
                },
            ])
        )

        expect(person).toEqual(postgresPersons[0])
    })

    test('updatePersonDeprecated', async () => {
        const uuid = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            false,
            uuid,
            ['distinct1', 'distinct2']
        )
        await delayUntilEventIngested(() => fetchClickHousePersons(teamId))
        await delayUntilEventIngested(() => fetchClickHouseDistinctIdValues(teamId, person.uuid), 2)

        // update properties and set is_identified to true
        await hub.db.updatePersonDeprecated(person, {
            properties: { replacedUserProp: 'propValue' },
            is_identified: true,
        })

        await delayUntilEventIngested(async () => (await fetchClickHousePersons(teamId)).filter((p) => p.is_identified))

        const clickHousePersons = await fetchClickHousePersons(teamId)
        const postgresPersons = await fetchPostgresPersons(teamId)

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
        const [updatedPerson] = await hub.db.updatePersonDeprecated(person, {
            created_at: randomDate,
            is_identified: false,
        })

        expect(updatedPerson.version).toEqual(2)

        await delayUntilEventIngested(async () =>
            (await fetchClickHousePersons(teamId)).filter((p) => !p.is_identified)
        )

        const clickHousePersons2 = await fetchClickHousePersons(teamId)
        const postgresPersons2 = await fetchPostgresPersons(teamId)

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
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid,
            ['distinct1']
        )
        const anotherPerson = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid2,
            ['another_distinct_id']
        )
        await delayUntilEventIngested(() => fetchClickHousePersons(teamId))
        const [postgresPerson] = await fetchPostgresPersons(teamId)

        await delayUntilEventIngested(() => fetchDistinctIdsClickhouse(teamId, postgresPerson.uuid), 1)
        await delayUntilEventIngested(() => fetchDistinctIdsClickhouse(teamId, postgresPerson.uuid), 1)
        const clickHouseDistinctIdValues = await fetchClickHouseDistinctIdValues(teamId, person.uuid)
        const postgresDistinctIdValues = await fetchDistinctIdValues(person.id)

        // check that all is in the right format

        expect(clickHouseDistinctIdValues).toEqual(['distinct1'])
        expect(postgresDistinctIdValues).toEqual(['distinct1'])

        const postgresDistinctIds = await hub.db.fetchDistinctIds(postgresPerson, Database.Postgres)
        const newClickHouseDistinctIdValues = await fetchDistinctIdsClickhouse(teamId, postgresPerson.uuid)

        expect(postgresDistinctIds).toEqual([
            expect.objectContaining({
                distinct_id: 'distinct1',
                person_id: person.id,
                team_id: teamId,
                version: '0',
            }),
        ])
        expect(newClickHouseDistinctIdValues).toEqual([
            {
                distinct_id: 'distinct1',
                person_id: person.uuid,
                team_id: teamId,
                version: 0,
                is_deleted: 0,
                _timestamp: expect.any(String),
                _offset: expect.any(Number),
                _partition: expect.any(Number),
            },
        ])

        // add 'anotherOne' to person

        await hub.db.addDistinctId(postgresPerson, 'anotherOne')

        await delayUntilEventIngested(() => fetchClickHouseDistinctIdValues(teamId, postgresPerson.uuid), 2)

        const clickHouseDistinctIdValues2 = await fetchClickHouseDistinctIdValues(teamId, postgresPerson.uuid)
        const postgresDistinctIdValues2 = await fetchDistinctIdValues(postgresPerson.id)

        expect(clickHouseDistinctIdValues2.sort()).toEqual(['distinct1', 'anotherOne'].sort())
        expect(postgresDistinctIdValues2).toEqual(['distinct1', 'anotherOne'])

        // check anotherPerson for their initial distinct id

        const clickHouseDistinctIdValuesOther = await fetchClickHouseDistinctIdValues(teamId, anotherPerson.uuid)
        const postgresDistinctIdValuesOther = await fetchDistinctIdValues(anotherPerson.id)

        expect(clickHouseDistinctIdValuesOther).toEqual(['another_distinct_id'])
        expect(postgresDistinctIdValuesOther).toEqual(['another_distinct_id'])
    })

    test('moveDistinctIds & deletePerson', async () => {
        const uuid = new UUIDT().toString()
        const uuid2 = new UUIDT().toString()
        const person = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            false,
            uuid,
            ['distinct1']
        )
        const anotherPerson = await hub.db.createPerson(
            DateTime.utc(),
            { userProp: 'propValue' },
            { userProp: PropertyUpdateOperation.Set },
            {},
            teamId,
            null,
            true,
            uuid2,
            ['another_distinct_id']
        )
        await delayUntilEventIngested(() => fetchClickHousePersons(teamId))
        const [postgresPerson] = await fetchPostgresPersons(teamId)

        await delayUntilEventIngested(() => fetchClickHouseDistinctIdValues(teamId, postgresPerson.uuid), 1)

        // move distinct ids from person to to anotherPerson

        const kafkaMessages = await hub.db.moveDistinctIds(person, anotherPerson)
        await hub.db!.kafkaProducer!.queueMessages(kafkaMessages)
        await delayUntilEventIngested(() => fetchClickHouseDistinctIdValues(teamId, anotherPerson.uuid), 2)

        // it got added

        // :TODO: Update version
        const clickHouseDistinctIdValuesMoved = await fetchClickHouseDistinctIdValues(teamId, anotherPerson.uuid)
        const postgresDistinctIdValuesMoved = await fetchDistinctIdValues(anotherPerson.id)
        const newClickHouseDistinctIds = await delayUntilEventIngested(
            () => fetchDistinctIdsClickhouse(teamId, anotherPerson.uuid),
            2
        )

        expect(postgresDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))
        expect(clickHouseDistinctIdValuesMoved).toEqual(expect.arrayContaining(['distinct1', 'another_distinct_id']))
        expect(newClickHouseDistinctIds).toEqual(
            expect.arrayContaining([
                {
                    distinct_id: 'another_distinct_id',
                    person_id: anotherPerson.uuid,
                    team_id: teamId,
                    version: 0,
                    is_deleted: 0,
                    _timestamp: expect.any(String),
                    _offset: expect.any(Number),
                    _partition: expect.any(Number),
                },
                {
                    distinct_id: 'distinct1',
                    person_id: anotherPerson.uuid,
                    team_id: teamId,
                    version: 1,
                    is_deleted: 0,
                    _timestamp: expect.any(String),
                    _offset: expect.any(Number),
                    _partition: expect.any(Number),
                },
            ])
        )

        // it got removed

        const clickHouseDistinctIdValuesRemoved = await hub.db.fetchDistinctIdValues(
            postgresPerson,
            Database.ClickHouse
        )
        const postgresDistinctIdValuesRemoved = await fetchDistinctIds(teamId, postgresPerson.id)
        const newClickHouseDistinctIdRemoved = await fetchDistinctIdsClickhouse(teamId, postgresPerson.uuid)

        expect(clickHouseDistinctIdValuesRemoved).toEqual([])
        expect(postgresDistinctIdValuesRemoved).toEqual([])
        expect(newClickHouseDistinctIdRemoved).toEqual([])

        // delete person

        await hub.db.postgresTransaction('', async (client) => {
            const deletePersonMessage = await hub.db.deletePerson(person, client)
            await hub.db!.kafkaProducer!.queueMessage(deletePersonMessage[0])
        })

        await delayUntilEventIngested(async () =>
            (await fetchClickHousePersons(teamId)).length === 1 ? ['deleted!'] : []
        )
        const clickHousePersons = await fetchClickHousePersons(teamId)
        const postgresPersons = await fetchPostgresPersons(teamId)

        expect(clickHousePersons.length).toEqual(1)
        expect(postgresPersons.length).toEqual(1)
    })
})
