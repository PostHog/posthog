import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { posthog } from '../../../src/utils/posthog'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/posthog', () => ({
    posthog: {
        identify: jest.fn(),
        capture: jest.fn(),
    },
}))

describe('GroupTypeManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let groupTypeManager: GroupTypeManager
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    beforeEach(async () => {
        ;({ teamId } = await resetTestDatabase())
        groupTypeManager = new GroupTypeManager(hub.db, hub.teamManager)

        jest.spyOn(hub.db.postgres, 'query')
        jest.spyOn(hub.db, 'insertGroupType')
    })

    afterAll(async () => {
        await closeHub()
    })

    describe('fetchGroupTypes()', () => {
        it('fetches and caches the group types', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())

            let groupTypes = await groupTypeManager.fetchGroupTypes(teamId)
            expect(groupTypes).toEqual({})

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await hub.db.insertGroupType(teamId, 'foo', 0)
            await hub.db.insertGroupType(teamId, 'bar', 1)

            jest.mocked(hub.db.postgres.query).mockClear()

            groupTypes = await groupTypeManager.fetchGroupTypes(teamId)

            expect(groupTypes).toEqual({})
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            groupTypes = await groupTypeManager.fetchGroupTypes(teamId)

            expect(groupTypes).toEqual({
                foo: 0,
                bar: 1,
            })
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
        })

        it('returns empty object if no groups are set up yet', async () => {
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({})
        })
    })

    describe('fetchGroupTypeIndex()', () => {
        it('fetches an already existing value', async () => {
            await hub.db.insertGroupType(teamId, 'foo', 0)
            await hub.db.insertGroupType(teamId, 'bar', 1)

            jest.mocked(hub.db.postgres.query).mockClear()
            jest.mocked(hub.db.insertGroupType).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'foo')).toEqual(0)
            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'bar')).toEqual(1)

            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
            expect(hub.db.insertGroupType).toHaveBeenCalledTimes(0)
            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it('inserts value if it does not exist yet at next index, resets cache', async () => {
            await hub.db.insertGroupType(teamId, 'foo', 0)

            jest.mocked(hub.db.insertGroupType).mockClear()
            jest.mocked(hub.db.postgres.query).mockClear()

            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'second')).toEqual(1)

            expect(hub.db.insertGroupType).toHaveBeenCalledTimes(1)
            expect(hub.db.postgres.query).toHaveBeenCalledTimes(3) // FETCH + INSERT + Team lookup

            const team = await hub.db.fetchTeam(teamId)
            expect(posthog.capture).toHaveBeenCalledWith({
                distinctId: 'plugin-server',
                event: 'group type ingested',
                properties: {
                    team: team!.uuid,
                    groupType: 'second',
                    groupTypeIndex: 1,
                },
                groups: {
                    project: team!.uuid,
                    organization: team!.organization_id,
                    instance: 'unknown',
                },
            })

            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'third')).toEqual(2)
            jest.mocked(hub.db.postgres.query).mockClear()

            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({
                foo: 0,
                second: 1,
                third: 2,
            })
            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'third')).toEqual(2)

            expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)
        })

        it('handles raciness for inserting a new group', async () => {
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({})

            await hub.db.insertGroupType(teamId, 'foo', 0) // Emulate another thread inserting foo
            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'second')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({
                foo: 0,
                second: 1,
            })
        })

        it('handles raciness for when same group type has already been inserted', async () => {
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({})

            // Emulate another thread inserting group types
            await hub.db.insertGroupType(teamId, 'foo', 0)
            await hub.db.insertGroupType(teamId, 'bar', 0)

            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'bar')).toEqual(1)
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({
                foo: 0,
                bar: 1,
            })
        })

        it('returns null once limit is met', async () => {
            await hub.db.insertGroupType(teamId, 'g0', 0)
            await hub.db.insertGroupType(teamId, 'g1', 1)
            await hub.db.insertGroupType(teamId, 'g2', 2)
            await hub.db.insertGroupType(teamId, 'g3', 3)
            await hub.db.insertGroupType(teamId, 'g4', 4)

            expect(await groupTypeManager.fetchGroupTypeIndex(teamId, 'new')).toEqual(null)
            expect(await groupTypeManager.fetchGroupTypes(teamId)).toEqual({
                g0: 0,
                g1: 1,
                g2: 2,
                g3: 3,
                g4: 4,
            })
        })
    })
})
