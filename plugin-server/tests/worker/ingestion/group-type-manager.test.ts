import { Hub, ProjectId } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { captureTeamEvent } from '../../../src/utils/posthog'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { createTeam, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/posthog', () => ({
    captureTeamEvent: jest.fn(),
}))

describe('GroupTypeManager()', () => {
    let hub: Hub
    let groupTypeManager: GroupTypeManager

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        groupTypeManager = new GroupTypeManager(hub.postgres, hub.teamManager)

        jest.spyOn(hub.db.postgres, 'query')
        jest.spyOn(groupTypeManager, 'insertGroupType')
    })
    afterEach(async () => {
        await closeHub(hub)
    })

    describe('fetchGroupTypes()', () => {
        it('fetches and caches the group types', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())

            let groupTypes = await groupTypeManager.fetchGroupTypes(2 as ProjectId)
            expect(groupTypes).toEqual({})

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'bar', 1)

            jest.mocked(hub.db.postgres.query).mockClear()

            groupTypes = await groupTypeManager.fetchGroupTypes(2 as ProjectId)

            expect(groupTypes).toEqual({})
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            groupTypes = await groupTypeManager.fetchGroupTypes(2 as ProjectId)

            expect(groupTypes).toEqual({
                foo: 0,
                bar: 1,
            })
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
        })

        it('fetches group types that have been inserted', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({})
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g0', 0)).toEqual([0, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g1', 1)).toEqual([1, true])
            groupTypeManager['groupTypesCache'].clear() // Clear cache
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({ g0: 0, g1: 1 })
        })

        it('handles conflicting by index when inserting and limits', async () => {
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g0', 0)).toEqual([0, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g1', 0)).toEqual([1, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g2', 0)).toEqual([2, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g3', 1)).toEqual([3, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g4', 0)).toEqual([4, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g5', 0)).toEqual([null, false])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g6', 0)).toEqual([null, false])

            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                g0: 0,
                g1: 1,
                g2: 2,
                g3: 3,
                g4: 4,
            })
        })

        it('handles conflict by name when inserting', async () => {
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'group_name', 0)).toEqual([0, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'group_name', 0)).toEqual([0, false])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'group_name', 0)).toEqual([0, false])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)).toEqual([1, true])
            expect(await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)).toEqual([1, false])

            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({ group_name: 0, foo: 1 })
        })
    })

    describe('fetchGroupTypeIndex()', () => {
        it('fetches an already existing value', async () => {
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'bar', 1)

            jest.mocked(hub.db.postgres.query).mockClear()
            jest.mocked(groupTypeManager.insertGroupType).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'foo')).toEqual(0)
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'bar')).toEqual(1)

            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
            expect(groupTypeManager.insertGroupType).toHaveBeenCalledTimes(0)
            expect(captureTeamEvent).not.toHaveBeenCalled()
        })

        it('inserts value if it does not exist yet at next index, resets cache', async () => {
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)

            jest.mocked(groupTypeManager.insertGroupType).mockClear()
            jest.mocked(hub.db.postgres.query).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'second')).toEqual(1)

            expect(groupTypeManager.insertGroupType).toHaveBeenCalledTimes(1)
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(3) // FETCH + INSERT + Team lookup

            const team = await hub.db.fetchTeam(2)
            expect(captureTeamEvent).toHaveBeenCalledWith(team, 'group type ingested', {
                groupType: 'second',
                groupTypeIndex: 1,
            })

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'third')).toEqual(2)
            jest.mocked(hub.db.postgres.query).mockClear()

            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                foo: 0,
                second: 1,
                third: 2,
            })
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'third')).toEqual(2)

            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
        })

        it('handles raciness for inserting a new group', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({})

            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0) // Emulate another thread inserting foo
            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                foo: 0,
                second: 1,
            })
        })

        it('handles raciness for when same group type has already been inserted for team and project', async () => {
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({})

            // Emulate another thread inserting group types, with both team and project the same
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'bar', 0)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'bar')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                foo: 0,
                bar: 1,
            })
        })

        it('handles raciness for when same group type has already been inserted for project', async () => {
            const otherTeamId = await createTeam(hub.postgres, 2 as ProjectId)

            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({})

            // Emulate another thread inserting group types, with the project the same
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'foo', 0)
            await groupTypeManager.insertGroupType(otherTeamId, 2 as ProjectId, 'bar', 0)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'bar')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                foo: 0,
                bar: 1,
            })
        })

        it('returns null once limit is met', async () => {
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g0', 0)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g1', 1)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g2', 2)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g3', 3)
            await groupTypeManager.insertGroupType(2, 2 as ProjectId, 'g4', 4)

            expect(await groupTypeManager.fetchGroupTypeIndex(2, 2 as ProjectId, 'new')).toEqual(null)
            expect(await groupTypeManager.fetchGroupTypes(2 as ProjectId)).toEqual({
                g0: 0,
                g1: 1,
                g2: 2,
                g3: 3,
                g4: 4,
            })
        })
    })
})
