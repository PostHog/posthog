import {
    buildInlineFiltersForCohorts,
    createCohort,
    createTeam,
    getFirstTeam,
    resetTestDatabase,
} from '../../tests/helpers/sql'
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

    describe('getRealtimeSupportedFiltersForTeam()', () => {
        it('returns empty array if no realtime cohorts exist', async () => {
            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('returns realtime supported filters for a team', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const conditionHash = 'test_hash_001'
            const filters = buildInlineFiltersForCohorts({ bytecode, conditionHash, type: 'event', key: '$browser' })

            // Create a realtime cohort
            const cohortId = await createCohort(postgres, teamId, 'Test Cohort', filters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                conditionHash: conditionHash,
                bytecode: bytecode,
                team_id: teamId,
                cohort_id: cohortId,
            })
        })

        it('filters out deleted cohorts', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const filters = buildInlineFiltersForCohorts({
                bytecode,
                conditionHash: 'test_hash_001',
                type: 'event',
                key: '$browser',
            })

            // Create active cohort
            await createCohort(postgres, teamId, 'Active Cohort', filters)

            // Create deleted cohort
            await createCohort(postgres, teamId, 'Deleted Cohort', filters, { deleted: true })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1)
            expect(result[0].cohort_id).not.toBe('Deleted Cohort')
        })

        it('filters out cohorts without filters', async () => {
            // Create cohort without filters (uses default empty filters)
            await createCohort(postgres, teamId, 'No Filters Cohort', null)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('filters out non-realtime cohorts', async () => {
            const bytecode = ['_H', 1, 32, 'test']
            const filters = buildInlineFiltersForCohorts({ bytecode, conditionHash: 'test_hash_001' })

            // Create behavioral cohort (not realtime)
            await createCohort(postgres, teamId, 'Behavioral Cohort', filters, { cohort_type: 'behavioral' })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toEqual([])
        })

        it('deduplicates filters by conditionHash across complex nested structures', async () => {
            const combinedBytecode = [
                '_H',
                1,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                31,
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                12,
                31,
                32,
                '$browser_language',
                32,
                'properties',
                1,
                2,
                12,
                3,
                2,
                3,
                2,
            ]
            const conditionHash = 'bcdc95b22cf3e527'

            // Complex filter structure matching the user's example
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event_multiple',
                                    bytecode: combinedBytecode,
                                    negation: false,
                                    operator: 'exact',
                                    event_type: 'events',
                                    conditionHash: conditionHash,
                                    event_filters: [
                                        { key: '$browser', type: 'event', value: 'is_set', operator: 'is_set' },
                                        {
                                            key: '$browser_language',
                                            type: 'event',
                                            value: 'is_set',
                                            operator: 'is_set',
                                        },
                                    ],
                                    operator_value: 5,
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            // Create two cohorts with the same conditionHash in complex structures
            await createCohort(postgres, teamId, 'Cohort 1', filters)
            await createCohort(postgres, teamId, 'Cohort 2', filters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1) // Should be deduplicated
            expect(result[0].conditionHash).toBe(conditionHash)
            expect(result[0].bytecode).toEqual(combinedBytecode)
        })

        it('handles multiple filters in single cohort with complex nested structure', async () => {
            // Complex filter: behavioral filter with event_filters (combined bytecode)
            const behavioralWithEventFilterBytecode = [
                '_H',
                1,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                31,
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                12,
                3,
                2,
            ]
            const pageviewOnlyBytecode = ['_H', 1, 32, '$pageleave', 32, 'event', 1, 1, 11]

            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event_multiple',
                                    bytecode: behavioralWithEventFilterBytecode,
                                    negation: false,
                                    operator: 'gte',
                                    event_type: 'events',
                                    conditionHash: '512ef57e6f504fc6',
                                    event_filters: [
                                        { key: '$browser', type: 'event', value: 'is_set', operator: 'is_set' },
                                    ],
                                    operator_value: 5,
                                    explicit_datetime: '-30d',
                                },
                                {
                                    key: '$pageleave',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: pageviewOnlyBytecode,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: 'e0418e34fcd847e5',
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(postgres, teamId, 'Multi-Filter Cohort', filters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result.map((f) => f.conditionHash).sort()).toEqual(['512ef57e6f504fc6', 'e0418e34fcd847e5'])
            // Verify the combined bytecode for the behavioral filter with event_filters
            const behavioralFilter = result.find((f) => f.conditionHash === '512ef57e6f504fc6')
            expect(behavioralFilter?.bytecode).toEqual(behavioralWithEventFilterBytecode)
        })

        it('filters out person property bytecodes explicitly via type in complex structure', async () => {
            const personPropBytecode = ['_H', 1, 31, 32, '$host', 32, 'properties', 32, 'person', 1, 3, 12]
            const behavioralBytecode = ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11]

            // Complex structure with both person and behavioral filters - only behavioral should be extracted
            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: behavioralBytecode,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: 'e0418e34fcd847e5',
                                    explicit_datetime: '-30d',
                                },
                                {
                                    key: '$host',
                                    type: 'person',
                                    bytecode: personPropBytecode,
                                    negation: false,
                                    operator: 'is_set',
                                    conditionHash: '30b9607b69c556bf',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(postgres, teamId, 'Mixed Filters Cohort', filters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            // Should only return the behavioral filter, not the person property filter
            expect(result).toHaveLength(1)
            expect(result[0].conditionHash).toBe('e0418e34fcd847e5')
            expect(result[0].bytecode).toEqual(behavioralBytecode)
        })

        it('handles complex OR structure with multiple filter groups', async () => {
            // Test structure with OR at top level containing multiple groups (matching user's second example)
            const pageviewWithBrowserBytecode = [
                '_H',
                1,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                31,
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                12,
                3,
                2,
            ]
            const pageleaveBytecode = ['_H', 1, 32, '$pageleave', 32, 'event', 1, 1, 11]
            const groupidentifyBytecode = [
                '_H',
                1,
                32,
                '$groupidentify',
                32,
                'event',
                1,
                1,
                11,
                31,
                32,
                'id',
                32,
                'properties',
                1,
                2,
                12,
                3,
                2,
            ]

            const filters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$pageview',
                                    type: 'behavioral',
                                    value: 'performed_event_multiple',
                                    bytecode: pageviewWithBrowserBytecode,
                                    negation: false,
                                    operator: 'gte',
                                    event_type: 'events',
                                    conditionHash: '512ef57e6f504fc6',
                                    event_filters: [
                                        { key: '$browser', type: 'event', value: 'is_set', operator: 'is_set' },
                                    ],
                                    operator_value: 5,
                                    explicit_datetime: '-30d',
                                },
                                {
                                    key: '$pageleave',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: pageleaveBytecode,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: 'e0418e34fcd847e5',
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                        {
                            type: 'OR',
                            values: [
                                {
                                    key: '$groupidentify',
                                    type: 'behavioral',
                                    value: 'performed_event',
                                    bytecode: groupidentifyBytecode,
                                    negation: false,
                                    event_type: 'events',
                                    conditionHash: 'f0bbe0140a9cfe05',
                                    event_filters: [{ key: 'id', type: 'event', value: 'is_set', operator: 'is_set' }],
                                    explicit_datetime: '-30d',
                                },
                            ],
                        },
                    ],
                },
            })

            await createCohort(postgres, teamId, 'Complex OR Cohort', filters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(3)
            const hashes = result.map((f) => f.conditionHash).sort()
            expect(hashes).toEqual(['512ef57e6f504fc6', 'e0418e34fcd847e5', 'f0bbe0140a9cfe05'])

            // Verify all bytecodes are correctly extracted
            expect(result.find((f) => f.conditionHash === '512ef57e6f504fc6')?.bytecode).toEqual(
                pageviewWithBrowserBytecode
            )
            expect(result.find((f) => f.conditionHash === 'e0418e34fcd847e5')?.bytecode).toEqual(pageleaveBytecode)
            expect(result.find((f) => f.conditionHash === 'f0bbe0140a9cfe05')?.bytecode).toEqual(groupidentifyBytecode)
        })

        it('handles malformed filters gracefully', async () => {
            const validBytecode = ['_H', 1, 32, 'test']
            const validFilters = buildInlineFiltersForCohorts({ bytecode: validBytecode, conditionHash: 'valid_hash' })

            // Create cohort with valid filters
            await createCohort(postgres, teamId, 'Valid Cohort', validFilters)

            // Create cohort with malformed filters (missing bytecode/conditionHash)
            const malformedFilters = JSON.stringify({
                properties: {
                    type: 'OR',
                    values: [
                        {
                            type: 'OR',
                            values: [
                                {
                                    key: '$test',
                                    type: 'behavioral',
                                    // Missing bytecode and conditionHash
                                },
                            ],
                        },
                    ],
                },
            })
            await createCohort(postgres, teamId, 'Malformed Cohort', malformedFilters)

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(1) // Only valid filter should be returned
            expect(result[0].conditionHash).toBe('valid_hash')
        })

        it('caches filters for subsequent calls', async () => {
            const bytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11]
            const filters = buildInlineFiltersForCohorts({
                bytecode,
                conditionHash: 'cached_hash',
                type: 'event',
                key: '$browser',
            })

            await createCohort(postgres, teamId, 'Cached Cohort', filters)

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
            const filters1 = buildInlineFiltersForCohorts({
                bytecode,
                conditionHash: 'team1_hash',
                type: 'event',
                key: '$browser',
            })
            const filters2 = buildInlineFiltersForCohorts({
                bytecode,
                conditionHash: 'team2_hash',
                type: 'event',
                key: '$browser',
            })

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts for both teams
            await createCohort(postgres, teamId, 'Team 1 Cohort', filters1)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', filters2)

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
            const filters = buildInlineFiltersForCohorts({
                bytecode,
                conditionHash: 'test_hash',
                type: 'event',
                key: '$browser',
            })

            await createCohort(postgres, teamId, 'Test Cohort', filters)

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
            const filters = buildInlineFiltersForCohorts({ bytecode, conditionHash: sharedHash })

            // Create another team
            const team = await hub.teamManager.getTeam(teamId)
            const team2Id = await createTeam(postgres, team!.organization_id)

            // Create cohorts with same conditionHash for both teams
            await createCohort(postgres, teamId, 'Team 1 Cohort', filters)
            await createCohort(postgres, team2Id, 'Team 2 Cohort', filters)

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

            const olderFilters = buildInlineFiltersForCohorts({ bytecode, conditionHash: 'older_hash' })
            const newerFilters = buildInlineFiltersForCohorts({ bytecode, conditionHash: 'newer_hash' })

            await createCohort(postgres, teamId, 'Older Cohort', olderFilters, {
                created_at: olderTime,
            })

            await createCohort(postgres, teamId, 'Newer Cohort', newerFilters, {
                created_at: newerTime,
            })

            const result = await realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeam(teamId)
            expect(result).toHaveLength(2)
            expect(result[0].conditionHash).toBe('newer_hash') // Should be first due to DESC order
            expect(result[1].conditionHash).toBe('older_hash')
        })
    })
})
