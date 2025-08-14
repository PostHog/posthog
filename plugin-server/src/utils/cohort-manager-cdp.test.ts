import { createCohort, createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { CohortManagerCDP } from './cohort-manager-cdp'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter } from './db/postgres'

describe('CohortManagerCDP()', () => {
    let hub: Hub
    let cohortManager: CohortManagerCDP
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchCohortsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        cohortManager = new CohortManagerCDP(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        fetchCohortsSpy = jest.spyOn(cohortManager as any, 'fetchCohorts')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('getCohortsForTeam()', () => {
        it('returns empty array if no cohorts exist', async () => {
            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toEqual([])
        })

        it('returns cohorts for a team', async () => {
            const bytecode = ['_H', 1, 32, 'test@example.com', 32, 'email', 32, 'person', 32, 'properties', 1, 2, 11]

            // Create a cohort
            const cohortId = await createCohort(postgres, teamId, 'Test Cohort', bytecode)

            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                id: cohortId,
                name: 'Test Cohort',
                team_id: teamId,
                bytecode,
                bytecode_error: null,
            })
        })

        it('filters out deleted cohorts', async () => {
            const bytecode = ['_H', 1, 32, 'test@example.com', 32, 'email', 32, 'person', 32, 'properties', 1, 2, 11]

            // Create active cohort
            await createCohort(postgres, teamId, 'Active Cohort', bytecode)

            // Create deleted cohort
            await createCohort(postgres, teamId, 'Deleted Cohort', bytecode, { deleted: true })

            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0].name).toBe('Active Cohort')
        })

        it('filters out cohorts without bytecode', async () => {
            // Create cohort without bytecode
            await createCohort(postgres, teamId, 'No Bytecode Cohort', null)

            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toEqual([])
        })

        it('filters out cohorts with bytecode errors', async () => {
            const bytecode = ['_H', 1, 32, 'test']

            // Create cohort with bytecode error
            await createCohort(postgres, teamId, 'Error Cohort', bytecode, {
                bytecode_error: 'Compilation failed',
            })

            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toEqual([])
        })

        it('caches cohorts for subsequent calls', async () => {
            const bytecode = ['_H', 1, 32, 'test@example.com', 32, 'email', 32, 'person', 32, 'properties', 1, 2, 11]

            await createCohort(postgres, teamId, 'Cached Cohort', bytecode)

            // First call
            const result1 = await cohortManager.getCohortsForTeam(teamId)
            expect(result1).toHaveLength(1)
            expect(fetchCohortsSpy).toHaveBeenCalledTimes(1)

            // Second call should use cache
            const result2 = await cohortManager.getCohortsForTeam(teamId)
            expect(result2).toHaveLength(1)
            expect(fetchCohortsSpy).toHaveBeenCalledTimes(1)
        })

        it('returns empty array for non-existent team', async () => {
            const result = await cohortManager.getCohortsForTeam(99999)
            expect(result).toEqual([])
        })
    })

    describe('getCohortsForTeams()', () => {
        it('returns cohorts for multiple teams', async () => {
            const bytecode = ['_H', 1, 32, 'test@example.com', 32, 'email', 32, 'person', 32, 'properties', 1, 2, 11]

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts for both teams
            await createCohort(postgres, teamId, 'Team 1 Cohort', bytecode)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', bytecode)

            const result = await cohortManager.getCohortsForTeams([teamId, team2Id])
            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(teamId)]![0].name).toBe('Team 1 Cohort')
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(team2Id)]![0].name).toBe('Team 2 Cohort')
        })

        it('returns empty arrays for teams with no cohorts', async () => {
            const result = await cohortManager.getCohortsForTeams([teamId, 99999])
            expect(result[String(teamId)]).toEqual([])
            expect(result['99999']).toEqual([])
        })

        it('efficiently loads multiple teams with single database call', async () => {
            const bytecode = ['_H', 1, 32, 'test@example.com', 32, 'email', 32, 'person', 32, 'properties', 1, 2, 11]

            await createCohort(postgres, teamId, 'Test Cohort', bytecode)

            const promises = [
                cohortManager.getCohortsForTeam(teamId),
                cohortManager.getCohortsForTeam(teamId),
                cohortManager.getCohortsForTeam(99999),
            ]

            const results = await Promise.all(promises)
            expect(fetchCohortsSpy).toHaveBeenCalledTimes(1)
            expect(results[0]).toHaveLength(1)
            expect(results[1]).toHaveLength(1)
            expect(results[2]).toHaveLength(0)
        })
    })

    describe('fetchCohorts()', () => {
        it('handles empty team ID array', async () => {
            const result = await (cohortManager as any).fetchCohorts([])
            expect(result).toEqual({})
        })

        it('handles invalid team IDs', async () => {
            const result = await (cohortManager as any).fetchCohorts(['invalid', 'NaN'])
            expect(result).toEqual({})
        })

        it('orders cohorts by team_id and id DESC', async () => {
            const bytecode1 = ['_H', 1, 32, 'test1']
            const bytecode2 = ['_H', 1, 32, 'test2']

            // Create cohorts with different IDs (higher ID should come first due to DESC order)
            const olderId = 1000
            const newerId = 2000

            await createCohort(postgres, teamId, 'Older Cohort', bytecode1, { id: olderId })
            await createCohort(postgres, teamId, 'Newer Cohort', bytecode2, { id: newerId })

            const result = await cohortManager.getCohortsForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result[0].name).toBe('Newer Cohort') // Should be first due to DESC order
            expect(result[1].name).toBe('Older Cohort')
        })

        it('groups cohorts by team_id correctly', async () => {
            const bytecode = ['_H', 1, 32, 'test']

            // Create multiple teams
            const team = await hub.teamManager.getTeam(teamId)
            const team1Id = await createTeam(postgres, team!.organization_id)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts for different teams
            await createCohort(postgres, team1Id, 'Team 1 Cohort A', bytecode)
            await createCohort(postgres, team1Id, 'Team 1 Cohort B', bytecode)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', bytecode)

            const result = await (cohortManager as any).fetchCohorts([String(team1Id), String(team2Id)])

            expect(result[String(team1Id)]).toHaveLength(2)
            expect(result[String(team2Id)]).toHaveLength(1)

            const team1Names = result[String(team1Id)].map((c: any) => c.name).sort()
            expect(team1Names).toEqual(['Team 1 Cohort A', 'Team 1 Cohort B'])
            expect(result[String(team2Id)][0].name).toBe('Team 2 Cohort')
        })
    })

    describe('LazyLoader integration', () => {
        it('uses LazyLoader with correct configuration', () => {
            // Verify LazyLoader is configured and initialized
            const lazyLoader = (cohortManager as any).lazyLoader
            expect(lazyLoader).toBeDefined()
            expect(lazyLoader.getCache).toBeDefined()
            expect(typeof lazyLoader.get).toBe('function')
            expect(typeof lazyLoader.getMany).toBe('function')
        })

        it('refreshes cache after configured time', async () => {
            const bytecode = ['_H', 1, 32, 'test']
            await createCohort(postgres, teamId, 'Test Cohort', bytecode)

            // First call
            await cohortManager.getCohortsForTeam(teamId)
            expect(fetchCohortsSpy).toHaveBeenCalledTimes(1)

            // Simulate time passing beyond refresh age
            const futureTime = Date.now() + 6 * 60 * 1000 // 6 minutes in the future
            jest.spyOn(Date, 'now').mockImplementation(() => futureTime)

            // Second call should trigger refresh
            await cohortManager.getCohortsForTeam(teamId)
            expect(fetchCohortsSpy).toHaveBeenCalledTimes(2)
        })
    })
})
