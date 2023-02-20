import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Group, Hub, Team } from '../../../src/types'
import { DB } from '../../../src/utils/db/db'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { upsertGroup } from '../../../src/worker/ingestion/properties-updater'
import { createPromise } from '../../helpers/promises'
import { getFirstTeam, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

describe('properties-updater', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    let team: Team
    const uuid = new UUIDT().toString()
    const distinctId = 'distinct_id_update_person_properties'

    const FUTURE_TIMESTAMP = DateTime.fromISO('2050-10-14T11:42:06.502Z')
    const PAST_TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z')

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        db = hub.db

        team = await getFirstTeam(hub)
        await db.createPerson(PAST_TIMESTAMP, {}, team.id, null, false, uuid, [distinctId])

        jest.spyOn(hub.db, 'updateGroup')
        jest.spyOn(hub.db, 'insertGroup')
    })

    afterEach(async () => {
        await closeServer()
    })

    describe('upsertGroup()', () => {
        async function upsert(properties: Properties, timestamp: DateTime) {
            await upsertGroup(hub.db, team.id, 0, 'group_key', properties, timestamp)
        }

        async function fetchGroup(): Promise<Group> {
            return (await hub.db.fetchGroup(team.id, 0, 'group_key'))!
        }

        it('creates a row if one does not yet exist with empty properties', async () => {
            await upsert({}, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({})
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).not.toHaveBeenCalled()
        })

        it('handles initial properties', async () => {
            await upsert({ foo: 'bar' }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({ foo: 'bar' })
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).not.toHaveBeenCalled()
        })

        it('handles updating properties as new ones come in', async () => {
            await upsert({ foo: 'bar', a: 1 }, PAST_TIMESTAMP)
            await upsert({ foo: 'zeta', b: 2 }, FUTURE_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: 'zeta', a: 1, b: 2 })
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).toHaveBeenCalledTimes(1)
        })

        it('handles updating when processing old events', async () => {
            await upsert({ foo: 'bar', a: 1 }, FUTURE_TIMESTAMP)
            await upsert({ foo: 'zeta', b: 2 }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: 'zeta', a: 1, b: 2 })
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).toHaveBeenCalledTimes(1)
        })

        it('handles updating when processing equal timestamped events', async () => {
            await upsert({ foo: '1' }, PAST_TIMESTAMP)
            await upsert({ foo: '2' }, PAST_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(2)
            expect(group.group_properties).toEqual({ foo: '2' })
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).toHaveBeenCalledTimes(1)
        })

        it('does nothing if newer timestamp but no properties change', async () => {
            await upsert({ foo: 'bar' }, PAST_TIMESTAMP)
            await upsert({ foo: 'bar' }, FUTURE_TIMESTAMP)

            const group = await fetchGroup()

            expect(group.version).toEqual(1)
            expect(group.group_properties).toEqual({ foo: 'bar' })
            expect(hub.db.insertGroup).toHaveBeenCalledTimes(1)
            expect(hub.db.updateGroup).not.toHaveBeenCalled()
        })

        it('handles race conditions as inserts happen in parallel', async () => {
            // :TRICKY: This test is closely coupled with the method under test and we
            //  control the timing of functions called precisely to emulate a race condition

            const firstFetchIsDonePromise = createPromise()
            const firstInsertShouldStartPromise = createPromise()

            jest.spyOn(db, 'insertGroup').mockImplementationOnce(async (...args) => {
                firstFetchIsDonePromise.resolve()
                await firstInsertShouldStartPromise.promise
                return await db.insertGroup(...args)
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
    })
})
