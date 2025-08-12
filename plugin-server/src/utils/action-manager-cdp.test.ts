import { createAction, createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { ActionManagerCDP } from './action-manager-cdp'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter } from './db/postgres'

describe('ActionManagerCDP()', () => {
    let hub: Hub
    let actionManager: ActionManagerCDP
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchActionsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        actionManager = new ActionManagerCDP(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        fetchActionsSpy = jest.spyOn(actionManager as any, 'fetchActions')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('getActionsForTeam()', () => {
        it('returns empty array if no actions exist', async () => {
            const result = await actionManager.getActionsForTeam(teamId)
            expect(result).toEqual([])
        })

        it('returns actions for a team', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]

            // Create an action
            const actionId = await createAction(postgres, teamId, 'Test Action', bytecode)

            const result = await actionManager.getActionsForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                id: actionId,
                name: 'Test Action',
                team_id: teamId,
                deleted: false,
                bytecode,
                bytecode_error: null,
            })
        })

        it('filters out deleted actions', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]

            // Create active action
            await createAction(postgres, teamId, 'Active Action', bytecode)

            // Create deleted action
            await createAction(postgres, teamId, 'Deleted Action', bytecode, { deleted: true })

            const result = await actionManager.getActionsForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('Active Action')
        })

        it('filters out actions without bytecode', async () => {
            // Create action without bytecode
            await createAction(postgres, teamId, 'No Bytecode Action', null)

            const result = await actionManager.getActionsForTeam(teamId)
            expect(result).toEqual([])
        })

        it('caches actions for subsequent calls', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]

            await createAction(postgres, teamId, 'Cached Action', bytecode)

            // First call
            const result1 = await actionManager.getActionsForTeam(teamId)
            expect(result1).toHaveLength(1)
            expect(fetchActionsSpy).toHaveBeenCalledTimes(1)

            // Second call should use cache
            const result2 = await actionManager.getActionsForTeam(teamId)
            expect(result2).toHaveLength(1)
            expect(fetchActionsSpy).toHaveBeenCalledTimes(1)
        })

        it('returns empty array for non-existent team', async () => {
            const result = await actionManager.getActionsForTeam(99999)
            expect(result).toEqual([])
        })
    })

    describe('getActionsForTeams()', () => {
        it('returns actions for multiple teams', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create actions for both teams
            await createAction(postgres, teamId, 'Team 1 Action', bytecode)
            await createAction(postgres, team2Id, 'Team 2 Action', bytecode)

            const result = await actionManager.getActionsForTeams([teamId, team2Id])
            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(teamId)]![0].name).toBe('Team 1 Action')
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(team2Id)]![0].name).toBe('Team 2 Action')
        })

        it('returns empty arrays for teams with no actions', async () => {
            const result = await actionManager.getActionsForTeams([teamId, 99999])
            expect(result[String(teamId)]).toEqual([])
            expect(result['99999']).toEqual([])
        })

        it('efficiently loads multiple teams with single database call', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]

            await createAction(postgres, teamId, 'Test Action', bytecode)

            const promises = [
                actionManager.getActionsForTeam(teamId),
                actionManager.getActionsForTeam(teamId),
                actionManager.getActionsForTeam(99999),
            ]

            const results = await Promise.all(promises)
            expect(fetchActionsSpy).toHaveBeenCalledTimes(1)
            expect(results[0]).toHaveLength(1)
            expect(results[1]).toHaveLength(1)
            expect(results[2]).toHaveLength(0)
        })
    })

    describe('fetchActions()', () => {
        it('handles empty team ID array', async () => {
            const result = await (actionManager as any).fetchActions([])
            expect(result).toEqual({})
        })

        it('handles invalid team IDs', async () => {
            const result = await (actionManager as any).fetchActions(['invalid', 'NaN'])
            expect(result).toEqual({})
        })

        it('orders actions by team_id and updated_at DESC', async () => {
            const bytecode = ['_H', 1, 32, 'test']

            // Create actions with different updated_at times
            const olderTime = new Date(Date.now() - 3600000).toISOString() // 1 hour ago
            const newerTime = new Date().toISOString()

            await createAction(postgres, teamId, 'Older Action', bytecode, {
                created_at: olderTime,
                updated_at: olderTime,
            })

            await createAction(postgres, teamId, 'Newer Action', bytecode, {
                created_at: newerTime,
                updated_at: newerTime,
            })

            const result = await actionManager.getActionsForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result[0].name).toBe('Newer Action') // Should be first due to DESC order
            expect(result[1].name).toBe('Older Action')
        })
    })
})
