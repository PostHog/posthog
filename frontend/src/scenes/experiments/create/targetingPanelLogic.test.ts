import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagFilters, FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { targetingPanelLogic } from './targetingPanelLogic'

function generateFilters(groups: FeatureFlagGroupType[]): FeatureFlagFilters {
    return { groups, aggregation_group_type_index: null }
}

describe('targetingPanelLogic', () => {
    let logic: ReturnType<typeof targetingPanelLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = targetingPanelLogic({
            id: 'test-experiment',
            filters: generateFilters([
                {
                    properties: [],
                    rollout_percentage: 100,
                    variant: null,
                },
            ]),
        })
        logic.mount()

        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [
                    200,
                    { users_affected: 150, total_users: 3000 },
                ],
            },
        })
    })

    describe('blast radius calculation', () => {
        it('loads blast radius on mount', async () => {
            logic?.unmount()

            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    {
                        properties: [
                            {
                                key: 'country',
                                value: 'US',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['calculateBlastRadius', 'setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: 150 },
                    totalUsers: 3000,
                })
        })

        it('loads blast radius for multiple condition sets', async () => {
            logic?.unmount()

            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    { properties: [], rollout_percentage: 100, variant: null },
                    {
                        properties: [
                            {
                                key: 'country',
                                value: 'US',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                    {
                        properties: [
                            {
                                key: 'plan',
                                value: 'premium',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 75,
                        variant: null,
                    },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['calculateBlastRadius', 'setAffectedUsers', 'setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    totalUsers: 3000,
                })

            // First condition set should have affected users calculated
            expect(logic.values.affectedUsers[0]).not.toBeUndefined()
        })

        it('updates blast radius when updating properties', async () => {
            logic?.unmount()
            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    {
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ]),
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(0, undefined, [
                    {
                        key: 'country',
                        value: 'US',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                    },
                ])
            })
                .delay(1100)
                .toDispatchActions(['setAffectedUsers', 'setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    totalUsers: 3000,
                })

            expect(logic.values.affectedUsers[0]).not.toBeUndefined()
        }, 15000)

        it('does not recalculate when only rollout percentage changes', async () => {
            jest.spyOn(api, 'create')

            logic?.unmount()
            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    {
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ]),
            })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['setAffectedUsers', 'setTotalUsers'])

            const callCountBefore = (api.create as jest.Mock).mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(0, 50)
            }).toNotHaveDispatchedActions(['setAffectedUsers', 'setTotalUsers'])

            expect(api.create).toHaveBeenCalledTimes(callCountBefore)
        })

        it('computes blast radius percentage accurately', () => {
            logic.actions.setAffectedUsers(0, 150)
            logic.actions.setAffectedUsers(1, 300)
            logic.actions.setAffectedUsers(2, 450)
            logic.actions.setTotalUsers(1500)

            expect(logic.values.computeBlastRadiusPercentage(100, 0)).toBeCloseTo(10, 2)
            expect(logic.values.computeBlastRadiusPercentage(50, 0)).toBeCloseTo(5, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 1)).toBeCloseTo(20, 2)
            expect(logic.values.computeBlastRadiusPercentage(75, 1)).toBeCloseTo(15, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBeCloseTo(30, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 2)).toBeCloseTo(9.9, 2)
        })

        it('handles missing blast radius data gracefully', () => {
            logic.actions.setAffectedUsers(0, -1)
            logic.actions.setAffectedUsers(1, undefined)
            logic.actions.setAffectedUsers(2, 50)

            expect(logic.values.computeBlastRadiusPercentage(100, 0)).toBe(100)
            expect(logic.values.computeBlastRadiusPercentage(50, 0)).toBe(50)

            expect(logic.values.computeBlastRadiusPercentage(100, 1)).toBe(100)
            expect(logic.values.computeBlastRadiusPercentage(75, 1)).toBe(75)

            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBe(100)

            logic.actions.setTotalUsers(200)
            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBeCloseTo(25, 2)
        })
    })

    describe('condition set management', () => {
        it('adds a new condition set with 100% rollout', () => {
            expect(logic.values.filters.groups).toHaveLength(1)

            logic.actions.setTotalUsers(3000)
            logic.actions.addConditionSet()

            expect(logic.values.filters.groups).toHaveLength(2)
            expect(logic.values.filters.groups[1].rollout_percentage).toBe(100)
            expect(logic.values.filters.groups[1].properties).toEqual([])
            expect(logic.values.affectedUsers[1]).toBe(3000)
        })

        it('removes a condition set and reindexes affected users', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null },
                { properties: [], rollout_percentage: 75, variant: null },
                { properties: [], rollout_percentage: 50, variant: null },
            ])
            logic.actions.setFilters(filters)

            logic.actions.setAffectedUsers(0, 100)
            logic.actions.setAffectedUsers(1, 200)
            logic.actions.setAffectedUsers(2, 300)

            logic.actions.removeConditionSet(0)

            expect(logic.values.filters.groups).toHaveLength(2)
            expect(logic.values.affectedUsers).toEqual({ 0: 200, 1: 300, 2: undefined })
        })

        it('duplicates a condition set', async () => {
            const filters = generateFilters([
                {
                    properties: [
                        {
                            key: 'country',
                            value: 'US',
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 75,
                    variant: null,
                    description: 'US users',
                },
            ])
            logic.actions.setFilters(filters)
            logic.actions.setAffectedUsers(0, 250)

            await expectLogic(logic, () => {
                logic.actions.duplicateConditionSet(0)
            }).delay(1100)

            expect(logic.values.filters.groups).toHaveLength(2)
            expect(logic.values.filters.groups[1].rollout_percentage).toBe(75)
            expect(logic.values.filters.groups[1].description).toBe('US users')
            expect(logic.values.filters.groups[1].properties).toHaveLength(1)
            expect(logic.values.filters.groups[1].sort_key).not.toBe(logic.values.filters.groups[0].sort_key)
            // Affected users are copied after a delay
            expect(logic.values.affectedUsers[1]).not.toBeUndefined()
        })

        it('updates rollout percentage', () => {
            logic.actions.updateConditionSet(0, 50)

            expect(logic.values.filters.groups[0].rollout_percentage).toBe(50)
        })

        it('updates properties', () => {
            logic.actions.updateConditionSet(0, undefined, [
                {
                    key: 'email',
                    value: 'test@example.com',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                },
            ])

            expect(logic.values.filters.groups[0].properties).toHaveLength(1)
            expect(logic.values.filters.groups[0].properties?.[0].key).toBe('email')
        })

        it('updates description', () => {
            logic.actions.updateConditionSet(0, undefined, undefined, 'Test description')

            expect(logic.values.filters.groups[0].description).toBe('Test description')
        })

        it('clears description when set to empty string', () => {
            const filters = generateFilters([
                {
                    properties: [],
                    rollout_percentage: 100,
                    variant: null,
                    description: 'Existing description',
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.updateConditionSet(0, undefined, undefined, '')

            expect(logic.values.filters.groups[0].description).toBe(null)
        })

        it('preserves whitespace in description', () => {
            logic.actions.updateConditionSet(0, undefined, undefined, '  Test description  ')

            expect(logic.values.filters.groups[0].description).toBe('  Test description  ')
        })
    })

    describe('moving condition sets', () => {
        it('moves a condition set up', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetUp(1)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
        })

        it('moves a condition set down', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetDown(0)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
        })

        it('does not move first condition set up', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetUp(0)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
            ])
        })

        it('does not move last condition set down', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetDown(1)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
            ])
        })

        it('swaps affected users when moving up', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.setAffectedUsers(0, 100)
            logic.actions.setAffectedUsers(1, 200)
            logic.actions.setAffectedUsers(2, 300)

            logic.actions.moveConditionSetUp(1)

            expect(logic.values.affectedUsers).toEqual({ 0: 200, 1: 100, 2: 300 })
        })

        it('swaps affected users when moving down', () => {
            const filters = generateFilters([
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.setAffectedUsers(0, 100)
            logic.actions.setAffectedUsers(1, 200)
            logic.actions.setAffectedUsers(2, 300)

            logic.actions.moveConditionSetDown(0)

            expect(logic.values.affectedUsers).toEqual({ 0: 200, 1: 100, 2: 300 })
        })

        it('preserves properties when moving', () => {
            const filters = generateFilters([
                {
                    properties: [
                        {
                            key: 'country',
                            value: 'US',
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 100,
                    variant: null,
                    sort_key: 'A',
                    description: 'US users',
                },
                {
                    properties: [
                        {
                            key: 'plan',
                            value: 'premium',
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 50,
                    variant: null,
                    sort_key: 'B',
                    description: 'Premium users',
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetUp(1)

            expect(logic.values.filters.groups[0].description).toBe('Premium users')
            expect(logic.values.filters.groups[0].properties?.[0].key).toBe('plan')
            expect(logic.values.filters.groups[1].description).toBe('US users')
            expect(logic.values.filters.groups[1].properties?.[0].key).toBe('country')
        })
    })

    describe('aggregation group type', () => {
        it('changes aggregation group type and resets filters', () => {
            const filters = generateFilters([
                {
                    properties: [
                        {
                            key: 'country',
                            value: 'US',
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 75,
                    variant: null,
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.setAggregationGroupTypeIndex(0)

            expect(logic.values.filters.aggregation_group_type_index).toBe(0)
            expect(logic.values.filters.groups).toHaveLength(1)
            expect(logic.values.filters.groups[0].properties).toEqual([])
            expect(logic.values.filters.groups[0].rollout_percentage).toBe(75)
        })

        it('preserves rollout percentage when changing aggregation type', () => {
            const filters = generateFilters([
                {
                    properties: [],
                    rollout_percentage: 50,
                    variant: null,
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.setAggregationGroupTypeIndex(1)

            expect(logic.values.filters.groups[0].rollout_percentage).toBe(50)
        })
    })

    describe('selectors', () => {
        it('returns correct aggregation target name for users', () => {
            expect(logic.values.aggregationTargetName).toBe('users')
        })

        it('returns correct taxonomic group types for users', () => {
            expect(logic.values.taxonomicGroupTypes).toContain('cohorts_with_all')
            expect(logic.values.taxonomicGroupTypes).toContain('person_properties')
            expect(logic.values.taxonomicGroupTypes).toContain('feature_flags')
        })

        it('returns correct taxonomic group types for groups', () => {
            logic.actions.setAggregationGroupTypeIndex(0)

            expect(logic.values.taxonomicGroupTypes).toContain('cohorts_with_all')
            expect(logic.values.taxonomicGroupTypes).toContain('feature_flags')
            expect(logic.values.taxonomicGroupTypes).toContain('groups_0')
        })
    })

    describe('onChange callback', () => {
        it('calls onChange when filters change', () => {
            const onChange = jest.fn()
            logic?.unmount()

            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    {
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ]),
                onChange,
            })
            logic.mount()

            logic.actions.updateConditionSet(0, 50)

            expect(onChange).toHaveBeenCalled()
        })

        it('calls onChange when adding a condition set', () => {
            const onChange = jest.fn()
            logic?.unmount()

            logic = targetingPanelLogic({
                id: 'test-experiment',
                filters: generateFilters([
                    {
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ]),
                onChange,
            })
            logic.mount()

            onChange.mockClear()
            logic.actions.addConditionSet()

            expect(onChange).toHaveBeenCalled()
        })
    })
})
