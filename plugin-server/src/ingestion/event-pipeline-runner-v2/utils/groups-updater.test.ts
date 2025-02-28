import { DateTime } from 'luxon'

import { DBHelpers } from '~/src/_tests/helpers/db'

import { createPromise } from '../../../_tests/helpers/promises'
import { getFirstTeam, resetTestDatabase } from '../../../_tests/helpers/sql'
import { MessageSizeTooLarge } from '../../../kafka/producer'
import { Group, Hub, Properties, Team } from '../../../types'
import { closeHub, createHub } from '../../../utils/hub'
import { UUIDT } from '../../../utils/utils'
import { upsertGroup } from './groups-updater'
import { PersonsDB } from './persons-db'

jest.mock('../../../utils/status')

describe('groups-updater', () => {
    let hub: Hub
    let dbHelpers: DBHelpers
    let personsDB: PersonsDB
    let team: Team
    const uuid = new UUIDT().toString()
    const distinctId = 'distinct_id_update_person_properties'

    const FUTURE_TIMESTAMP = DateTime.fromISO('2050-10-14T11:42:06.502Z')
    const PAST_TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z')

    let postgresQuerySpy: jest.SpyInstance
    let actualQuery: (...args: any[]) => Promise<any>
    const getSqlCallsType = () => postgresQuerySpy.mock.calls.map((x) => x[1].trim().split(' ')[0])

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        dbHelpers = new DBHelpers(hub)
        personsDB = new PersonsDB(hub.postgres, hub.kafkaProducer)

        team = await getFirstTeam(hub)
        await personsDB.createPerson(PAST_TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, [{ distinctId }])

        actualQuery = hub.postgres.query

        postgresQuerySpy = jest.spyOn(hub.postgres, 'query')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('upsertGroup()', () => {
        async function upsert(properties: Properties, timestamp: DateTime) {
            await upsertGroup(hub, team.id, team.project_id, 0, 'group_key', properties, timestamp)
        }

        async function fetchGroup(): Promise<Group> {
            return (await dbHelpers.fetchGroup(team.id, 0, 'group_key'))!
        }

        it('creates a row if one does not yet exist with empty properties', async () => {
            await upsert({}, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({})
            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                ]
            `)
        })

        it('handles initial properties', async () => {
            await upsert({ foo: 'bar' }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({ foo: 'bar' })

            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                ]
            `)
        })

        it('handles updating properties as new ones come in', async () => {
            await upsert({ foo: 'bar', a: 1 }, PAST_TIMESTAMP)
            await upsert({ foo: 'zeta', b: 2 }, FUTURE_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: 'zeta', a: 1, b: 2 })

            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                  "UPDATE",
                  "SELECT",
                ]
            `)
        })

        it('handles updating when processing old events', async () => {
            await upsert({ foo: 'bar', a: 1 }, FUTURE_TIMESTAMP)
            await upsert({ foo: 'zeta', b: 2 }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: 'zeta', a: 1, b: 2 })

            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                  "UPDATE",
                  "SELECT",
                ]
            `)
        })

        it('handles updating when processing equal timestamped events', async () => {
            await upsert({ foo: '1' }, PAST_TIMESTAMP)
            await upsert({ foo: '2' }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: '2' })
            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                  "UPDATE",
                  "SELECT",
                ]
            `)
        })

        it('does nothing if newer timestamp but no properties change', async () => {
            await upsert({ foo: 'bar' }, PAST_TIMESTAMP)
            await upsert({ foo: 'bar' }, FUTURE_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({ foo: 'bar' })

            expect(getSqlCallsType()).toMatchInlineSnapshot(`
                [
                  "SELECT",
                  "INSERT",
                  "SELECT",
                  "SELECT",
                ]
            `)
        })

        it('handles race conditions as inserts happen in parallel', async () => {
            // :TRICKY: This test is closely coupled with the method under test and we
            //  control the timing of functions called precisely to emulate a race condition

            const firstFetchIsDonePromise = createPromise()
            const firstInsertShouldStartPromise = createPromise()

            jest.spyOn(hub.postgres, 'query').mockImplementationOnce(async (...args) => {
                firstFetchIsDonePromise.resolve()
                await firstInsertShouldStartPromise.promise
                return await actualQuery(...args)
            })

            // First, we start first update, and wait until first fetch is done (and returns that group does not exist)
            const firstUpsertPromise = upsert({ a: 1, b: 2 }, PAST_TIMESTAMP)
            await firstFetchIsDonePromise.promise

            // Second, we do a another (complete) upsert in-between which creates a row in groups table
            await upsert({ a: 3, d: 3 }, FUTURE_TIMESTAMP)

            // Third, we continue with the original upsert, and wait for the end
            firstInsertShouldStartPromise.resolve()
            await firstUpsertPromise

            // Verify the results
            const group = await fetchGroup()
            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ a: 1, b: 2, d: 3 })
        })

        it('handles message size too large errors', async () => {
            jest.spyOn(hub.kafkaProducer, 'queueMessages').mockImplementationOnce((): Promise<void> => {
                const error = new Error('message size too large')
                throw new MessageSizeTooLarge(error.message, error)
            })

            await expect(upsert({ a: 1, b: 2 }, PAST_TIMESTAMP)).resolves.toEqual(undefined)
        })
    })
})
