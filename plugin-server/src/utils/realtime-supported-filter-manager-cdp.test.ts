import { createCohort, createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter } from './db/postgres'
import { RealtimeSupportedFilterManagerCDP } from './realtime-supported-filter-manager-cdp'

describe('RealtimeSupportedFilterManagerCDP()', () => {
    let hub: Hub
    let realtimeSupportedFilterManager: RealtimeSupportedFilterManagerCDP
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchRealtimeSupportedFiltersSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        realtimeSupportedFilterManager = new RealtimeSupportedFilterManagerCDP(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        fetchRealtimeSupportedFiltersSpy = jest.spyOn(
            realtimeSupportedFilterManager as any,
            'fetchRealtimeSupportedFilters'
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    // Helper function to create compiled_bytecode array from bytecode
    const createCompiledBytecode = (
        bytecode: any[],
        conditionHash: string,
        filterPath: string = 'properties.values[0]',
        extra?: Record<string, any>
    ) => {
        return [
            {
                filter_path: filterPath,
                bytecode: bytecode,
                conditionHash: conditionHash,
                ...(extra || {}),
            },
        ]
    }

    describe('getRealtimeSupportedFiltersForTeam()', () => {
        it('returns empty array if no realtime cohorts exist', async () => {
            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('returns realtime supported filters for a team', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const conditionHash = 'test_hash_001'
            const compiledBytecode = createCompiledBytecode(bytecode, conditionHash)

            // Create a realtime cohort
            const cohortId = await createCohort(postgres, teamId, 'Test Cohort', compiledBytecode)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                conditionHash: conditionHash,
                bytecode: bytecode,
                team_id: teamId,
                cohort_id: cohortId,
                filter_path: 'properties.values[0]',
            })
        })

        it('filters out deleted cohorts', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const compiledBytecode = createCompiledBytecode(bytecode, 'test_hash_001')

            // Create active cohort
            await createCohort(postgres, teamId, 'Active Cohort', compiledBytecode)

            // Create deleted cohort
            await createCohort(postgres, teamId, 'Deleted Cohort', compiledBytecode, { deleted: true })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0].cohort_id).not.toBe('Deleted Cohort')
        })

        it('filters out cohorts without compiled_bytecode', async () => {
            // Create cohort without compiled_bytecode
            await createCohort(postgres, teamId, 'No Bytecode Cohort', null)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('filters out non-realtime cohorts', async () => {
            const bytecode = ['_H', 1, 32, 'test']
            const compiledBytecode = createCompiledBytecode(bytecode, 'test_hash_001')

            // Create behavioral cohort (not realtime)
            await createCohort(postgres, teamId, 'Behavioral Cohort', compiledBytecode, { cohort_type: 'behavioral' })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('deduplicates filters by conditionHash', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const conditionHash = 'duplicate_hash'
            const compiledBytecode = createCompiledBytecode(bytecode, conditionHash)

            // Create two cohorts with the same conditionHash
            await createCohort(postgres, teamId, 'Cohort 1', compiledBytecode)
            await createCohort(postgres, teamId, 'Cohort 2', compiledBytecode)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1) // Should be deduplicated
            expect(result[0].conditionHash).toBe(conditionHash)
        })

        it('handles multiple filters in single cohort', async () => {
            const bytecode1 = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const bytecode2 = ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11]

            const compiledBytecode = [
                {
                    filter_path: 'properties.values[0]',
                    bytecode: bytecode1,
                    conditionHash: 'hash_001',
                },
                {
                    filter_path: 'properties.values[1]',
                    bytecode: bytecode2,
                    conditionHash: 'hash_002',
                },
            ]

            await createCohort(postgres, teamId, 'Multi-Filter Cohort', compiledBytecode)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result.map((f) => f.conditionHash).sort()).toEqual(['hash_001', 'hash_002'])
        })

        it('filters out person property bytecodes explicitly via filter_type', async () => {
            const personPropBytecode = ['_H', 1, 31, 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 12]
            const compiledBytecode = createCompiledBytecode(personPropBytecode, 'person_hash', 'properties.values[0]', {
                filter_type: 'person',
            })

            await createCohort(postgres, teamId, 'Person Prop Cohort', compiledBytecode)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('handles malformed compiled_bytecode gracefully', async () => {
            const validBytecode = ['_H', 1, 32, 'test']
            const validCompiledBytecode = createCompiledBytecode(validBytecode, 'valid_hash')

            // Create cohort with valid bytecode
            await createCohort(postgres, teamId, 'Valid Cohort', validCompiledBytecode)

            // Create cohort with malformed bytecode
            await createCohort(postgres, teamId, 'Malformed Cohort', [
                {
                    // Missing required fields
                    filter_path: 'properties.values[0]',
                    // Missing bytecode and conditionHash
                },
            ])

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1) // Only valid filter should be returned
            expect(result[0].conditionHash).toBe('valid_hash')
        })

        it('caches filters for subsequent calls', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const compiledBytecode = createCompiledBytecode(bytecode, 'cached_hash')

            await createCohort(postgres, teamId, 'Cached Cohort', compiledBytecode)

            // First call
            const result1 = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result1).toHaveLength(1)
            expect(fetchRealtimeSupportedFiltersSpy).toHaveBeenCalledTimes(1)

            // Second call should use cache
            const result2 = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result2).toHaveLength(1)
            expect(fetchRealtimeSupportedFiltersSpy).toHaveBeenCalledTimes(1)
        })

        it('returns empty array for non-existent team', async () => {
            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(99999)
            expect(result).toEqual([])
        })
    })

    describe('getRealtimeSupportedFiltersForTeams()', () => {
        it('returns filters for multiple teams', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const compiledBytecode1 = createCompiledBytecode(bytecode, 'team1_hash')
            const compiledBytecode2 = createCompiledBytecode(bytecode, 'team2_hash')

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts for both teams
            await createCohort(postgres, teamId, 'Team 1 Cohort', compiledBytecode1)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', compiledBytecode2)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeams([teamId, team2Id])
            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(teamId)]![0].conditionHash).toBe('team1_hash')
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(team2Id)]![0].conditionHash).toBe('team2_hash')
        })

        it('returns empty arrays for teams with no realtime cohorts', async () => {
            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeams([teamId, 99999])
            expect(result[String(teamId)]).toEqual([])
            expect(result['99999']).toEqual([])
        })

        it('efficiently loads multiple teams with single database call', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const compiledBytecode = createCompiledBytecode(bytecode, 'test_hash')

            await createCohort(postgres, teamId, 'Test Cohort', compiledBytecode)

            const promises = [
                realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId),
                realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId),
                realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(99999),
            ]

            const results = await Promise.all(promises)
            expect(fetchRealtimeSupportedFiltersSpy).toHaveBeenCalledTimes(1)
            expect(results[0]).toHaveLength(1)
            expect(results[1]).toHaveLength(1)
            expect(results[2]).toHaveLength(0)
        })

        it('deduplicates filters across multiple teams', async () => {
            const bytecode = ['_H', 1, 32, 'shared', 32, 'filter']
            const sharedHash = 'shared_condition_hash'
            const compiledBytecode = createCompiledBytecode(bytecode, sharedHash)

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts with same conditionHash for both teams
            await createCohort(postgres, teamId, 'Team 1 Cohort', compiledBytecode)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', compiledBytecode)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeams([teamId, team2Id])

            // Should be deduplicated - only one filter per team even though they have same hash
            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(teamId)]![0].conditionHash).toBe(sharedHash)
            expect(result[String(team2Id)]![0].conditionHash).toBe(sharedHash)
        })
    })

    describe('fetchRealtimeSupportedFilters()', () => {
        it('handles empty team ID array', async () => {
            const result = await (realtimeSupportedFilterManager as any).fetchRealtimeSupportedFilters([])
            expect(result).toEqual({})
        })

        it('handles invalid team IDs', async () => {
            const result = await (realtimeSupportedFilterManager as any).fetchRealtimeSupportedFilters([
                'invalid',
                'NaN',
            ])
            expect(result).toEqual({})
        })

        it('orders cohorts by team_id and created_at DESC', async () => {
            const bytecode = ['_H', 1, 32, 'test']

            // Create cohorts with different created_at times
            const olderTime = new Date(Date.now() - 3600000).toISOString() // 1 hour ago
            const newerTime = new Date().toISOString()

            const olderCompiledBytecode = createCompiledBytecode(bytecode, 'older_hash')
            const newerCompiledBytecode = createCompiledBytecode(bytecode, 'newer_hash')

            await createCohort(postgres, teamId, 'Older Cohort', olderCompiledBytecode, {
                created_at: olderTime,
            })

            await createCohort(postgres, teamId, 'Newer Cohort', newerCompiledBytecode, {
                created_at: newerTime,
            })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result[0].conditionHash).toBe('newer_hash') // Should be first due to DESC order
            expect(result[1].conditionHash).toBe('older_hash')
        })
    })
})
