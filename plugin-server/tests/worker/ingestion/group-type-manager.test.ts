import { mocked } from 'ts-jest/utils'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

describe('GroupTypeManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let groupTypeManager: GroupTypeManager

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        groupTypeManager = new GroupTypeManager(hub.db)

        jest.spyOn(hub.db, 'postgresQuery')
        jest.spyOn(hub.db, 'insertGroupType')
    })
    afterEach(async () => {
        await closeHub()
    })

    describe('fetchGroupTypes()', () => {
        it('fetches and caches the group types', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())

            let groupTypes = await groupTypeManager.fetchGroupTypes(2)
            expect(groupTypes).toEqual({})

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await hub.db.insertGroupType(2, 'foo', 0)
            await hub.db.insertGroupType(2, 'bar', 1)

            mocked(hub.db.postgresQuery).mockClear()

            groupTypes = await groupTypeManager.fetchGroupTypes(2)

            expect(groupTypes).toEqual({})
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            groupTypes = await groupTypeManager.fetchGroupTypes(2)

            expect(groupTypes).toEqual({
                foo: 0,
                bar: 1,
            })
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('returns empty object if no groups are set up yet', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({})
        })
    })

    describe('fetchGroupTypeIndex()', () => {
        it('fetches an already existing value', async () => {
            await hub.db.insertGroupType(2, 'foo', 0)
            await hub.db.insertGroupType(2, 'bar', 1)

            mocked(hub.db.postgresQuery).mockClear()
            mocked(hub.db.insertGroupType).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'foo')).toEqual(0)
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'bar')).toEqual(1)

            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
            expect(hub.db.insertGroupType).toHaveBeenCalledTimes(0)
        })

        it('inserts value if it does not exist yet at next index, resets cache', async () => {
            await hub.db.insertGroupType(2, 'foo', 0)

            mocked(hub.db.insertGroupType).mockClear()
            mocked(hub.db.postgresQuery).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'second')).toEqual(1)

            expect(hub.db.insertGroupType).toHaveBeenCalledTimes(1)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(2)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'third')).toEqual(2)
            mocked(hub.db.postgresQuery).mockClear()

            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({
                foo: 0,
                second: 1,
                third: 2,
            })
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'third')).toEqual(2)

            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('handles raciness for inserting a new group', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({})

            await hub.db.insertGroupType(2, 'foo', 0) // Emulate another thread inserting foo
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({
                foo: 0,
                second: 1,
            })
        })

        it('handles raciness for when same group type has already been inserted', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({})

            // Emulate another thread inserting group types
            await hub.db.insertGroupType(2, 'foo', 0)
            await hub.db.insertGroupType(2, 'bar', 0)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'bar')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({
                foo: 0,
                bar: 1,
            })
        })

        it('returns null once limit is met', async () => {
            await hub.db.insertGroupType(2, 'g0', 0)
            await hub.db.insertGroupType(2, 'g1', 1)
            await hub.db.insertGroupType(2, 'g2', 2)
            await hub.db.insertGroupType(2, 'g3', 3)
            await hub.db.insertGroupType(2, 'g4', 4)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 'new')).toEqual(null)
            expect(await groupTypeManager.fetchGroupTypes(2)).toEqual({
                g0: 0,
                g1: 1,
                g2: 2,
                g3: 3,
                g4: 4,
            })
        })
    })
})
