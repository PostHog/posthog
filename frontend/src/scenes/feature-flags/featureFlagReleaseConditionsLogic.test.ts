import { expectLogic } from 'kea-test-utils'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AnyPropertyFilter,
    FeatureFlagGroupType,
    FeatureFlagType,
    MultivariateFlagOptions,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { featureFlagReleaseConditionsLogic } from './featureFlagReleaseConditionsLogic'

jest.mock('uuid', () => ({
    v4: jest.fn(),
}))

function generateFeatureFlagFilters(
    groups: FeatureFlagGroupType[],
    multivariate?: MultivariateFlagOptions
): FeatureFlagType['filters'] {
    return { groups, multivariate: multivariate ?? null, payloads: {} }
}

describe('the feature flag release conditions logic', () => {
    let logic: ReturnType<typeof featureFlagReleaseConditionsLogic.build>
    let nextUuid: string

    beforeEach(() => {
        initKeaTests()

        jest.clearAllMocks()

        nextUuid = 'A'
        ;(uuidv4 as jest.Mock).mockImplementation(() => {
            const uuid = nextUuid
            nextUuid = String.fromCharCode(nextUuid.charCodeAt(0) + 1)
            return uuid
        })

        logic = featureFlagReleaseConditionsLogic({
            id: '1234',
            filters: generateFeatureFlagFilters([
                {
                    properties: [],
                    rollout_percentage: 50,
                    sort_key: 'group-1',
                    variant: null,
                },
            ]),
        })
        logic.mount()

        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 120, total: 2000 }],
            },
        })
    })

    describe('computing blast radius', () => {
        it('loads when editing a flag', async () => {
            // clear existing logic
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                filters: generateFeatureFlagFilters([
                    {
                        properties: [
                            {
                                key: 'aloha',
                                value: 'aloha',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                        sort_key: 'A',
                    },
                ]),
            })
            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['calculateBlastRadius', 'setAffectedCount', 'setTotalCount'])
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 120 },
                    totalCounts: { A: 2000 },
                })
        })

        it('loads when editing a flag with multiple conditions', async () => {
            // clear existing logic
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 86, variant: null, sort_key: 'A' },
                    {
                        properties: [
                            {
                                key: 'aloha',
                                value: 'aloha',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                        sort_key: 'B',
                    },
                    {
                        properties: [
                            {
                                key: 'aloha',
                                value: 'aloha2',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 75,
                        variant: null,
                        sort_key: 'C',
                    },
                    {
                        properties: [
                            {
                                key: 'aloha',
                                value: 'aloha3',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 86,
                        variant: null,
                        sort_key: 'D',
                    },
                ]),
            })
            await expectLogic(logic, () => {
                jest.spyOn(api, 'create')
                    .mockReturnValueOnce(Promise.resolve({ affected: 140, total: 2000 }))
                    .mockReturnValueOnce(Promise.resolve({ affected: 240, total: 2002 }))
                    .mockReturnValueOnce(Promise.resolve({ affected: 500, total: 2000 }))
                    .mockReturnValueOnce(Promise.resolve({ affected: 750, total: 2001 }))

                logic.mount()
            })
                .toDispatchActions([
                    'setAffectedCount',
                    'setTotalCount',
                    'setAffectedCount',
                    'setTotalCount',
                    'setAffectedCount',
                    'setTotalCount',
                    'setAffectedCount',
                    'setTotalCount',
                ])
                .toMatchValues({
                    affectedCounts: { A: undefined, B: undefined, C: undefined, D: undefined },
                    totalCounts: { A: undefined, B: undefined, C: undefined, D: undefined },
                })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 140, B: undefined, C: undefined, D: undefined },
                    totalCounts: { A: 2000, B: undefined, C: undefined, D: undefined },
                })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 140, B: 240, C: undefined, D: undefined },
                    totalCounts: { A: 2000, B: 2002, C: undefined, D: undefined },
                })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 140, B: 240, C: 500, D: undefined },
                    totalCounts: { A: 2000, B: 2002, C: 2000, D: undefined },
                })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 140, B: 240, C: 500, D: 750 },
                    totalCounts: { A: 2000, B: 2002, C: 2000, D: 2001 },
                })
        })

        it('updates when adding conditions to a flag', async () => {
            jest.spyOn(api, 'create')
                // Mount: calculateBlastRadiusForCondition('A', []) makes an API call
                // because [].some(isEmptyProperty) is false (no elements to test)
                .mockReturnValueOnce(Promise.resolve({ affected: 2000, total: 2000 }))
                // updateConditionSet for A with complete properties
                .mockReturnValueOnce(Promise.resolve({ affected: 124, total: 2000 }))
                // addConditionSet: calculateBlastRadiusForCondition('B', []) makes an API call
                .mockReturnValueOnce(Promise.resolve({ affected: 2000, total: 2000 }))
                // updateConditionSet for B with complete properties
                .mockReturnValueOnce(Promise.resolve({ affected: 248, total: 2000 }))

            logic = featureFlagReleaseConditionsLogic({
                id: '5678',
                filters: generateFeatureFlagFilters([
                    {
                        properties: [],
                        rollout_percentage: 50,
                        variant: null,
                        sort_key: 'A',
                    },
                ]),
            })

            // Mount triggers calculateBlastRadiusForCondition for condition A (empty props → API call).
            // Use toDispatchActions (not toFinishAllListeners) to advance historyIndex past mount's actions.
            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])

            // Update with incomplete property — clears counts but no API call
            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(0, 20, [
                    {
                        key: 'aloha',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: null,
                    },
                ])
            }).toDispatchActions(['setAffectedCount', 'setTotalCount'])

            // Update with complete property — triggers API call after debounce
            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(0, 20, [
                    {
                        key: 'aloha',
                        value: 'aloha',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                    },
                ])
            })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 124 },
                    totalCounts: { A: 2000 },
                })

            // Add condition B — triggers calculateBlastRadiusForCondition('B', []) → API call
            await expectLogic(logic, () => {
                nextUuid = 'B'
                logic.actions.addConditionSet()
            })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])

            // Update condition B with complete property
            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(1, 20, [
                    {
                        key: 'aloha',
                        value: 'aloha',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                    },
                ])
            })
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                .toMatchValues({
                    affectedCounts: { A: 124, B: 248 },
                    totalCounts: { A: 2000, B: 2000 },
                })

            // Remove condition A — no blast radius recalculation
            await expectLogic(logic, () => {
                logic.actions.removeConditionSet(0)
            })
                .toNotHaveDispatchedActions(['setAffectedCount'])
                .toMatchValues({
                    affectedCounts: { A: 124, B: 248 },
                })
        })

        it('uses explicit sortKey when provided to addConditionSet', async () => {
            jest.spyOn(api, 'create')
                .mockReturnValueOnce(Promise.resolve({ affected: 500, total: 1000 }))
                .mockReturnValueOnce(Promise.resolve({ affected: 500, total: 1000 }))

            const testLogic = featureFlagReleaseConditionsLogic({
                id: 'sortkey-test',
                filters: generateFeatureFlagFilters([
                    {
                        properties: [],
                        rollout_percentage: 100,
                        variant: null,
                        sort_key: 'initial',
                    },
                ]),
            })
            testLogic.mount()

            const explicitSortKey = 'my-custom-sort-key'
            await expectLogic(testLogic, () => {
                testLogic.actions.addConditionSet(explicitSortKey)
            }).toDispatchActions(['setAffectedCount'])

            // Verify the new condition set has the explicit sortKey
            expect(testLogic.values.filterGroups[1].sort_key).toBe(explicitSortKey)

            testLogic.unmount()
        })

        it('computes blast radius percentages accurately', async () => {
            logic.actions.setAffectedCount('A', 100)
            logic.actions.setAffectedCount('B', 200)
            logic.actions.setAffectedCount('C', 346)
            logic.actions.setTotalCount('A', 1000)
            logic.actions.setTotalCount('B', 1000)
            logic.actions.setTotalCount('C', 1000)

            expect(logic.values.computeBlastRadiusPercentage(20, 'A')).toBeCloseTo(2, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 'A')).toBeCloseTo(3.3, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 'B')).toBeCloseTo(10, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 'B')).toBeCloseTo(20, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(34.6, 2)
            expect(logic.values.computeBlastRadiusPercentage(67, 'C')).toBeCloseTo(23.182, 2)
        })

        it('computes blast radius percentages accurately with missing information', async () => {
            logic.actions.setAffectedCount('A', -1)
            logic.actions.setAffectedCount('B', undefined)
            logic.actions.setAffectedCount('C', 25)
            // total users is null as well

            expect(logic.values.computeBlastRadiusPercentage(20, 'A')).toBeCloseTo(20, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 'A')).toBeCloseTo(33, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 'B')).toBeCloseTo(50, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 'B')).toBeCloseTo(100, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(100, 2)
            expect(logic.values.computeBlastRadiusPercentage(10, 'C')).toBeCloseTo(10, 2)

            logic.actions.setTotalCount('A', 100)
            logic.actions.setTotalCount('B', 100)
            logic.actions.setTotalCount('C', 100)
            expect(logic.values.computeBlastRadiusPercentage(67, 'A')).toBeCloseTo(67, 2)
            // total is defined but affected is not. UI side should handle not showing the result in this case
            // and computation resolves to rollout percentage
            expect(logic.values.computeBlastRadiusPercentage(75, 'B')).toEqual(75)
            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(25, 2)

            logic.actions.setTotalCount('A', 500_000_000)
            logic.actions.setTotalCount('C', 500_000_000)
            logic.actions.setAffectedCount('A', 249_999_000)
            expect(logic.values.computeBlastRadiusPercentage(100, 'A')).toEqual(49.9998)
            expect(logic.values.computeBlastRadiusPercentage(5, 'C')).toEqual(0)
        })

        it('sends condition-level aggregation_group_type_index to blast radius API', async () => {
            logic?.unmount()

            const createSpy = jest.spyOn(api, 'create').mockImplementation((_url, data: any) => {
                if (data?.group_type_index != null) {
                    return Promise.resolve({
                        affected: 10,
                        total: 100,
                    })
                }
                return Promise.resolve({
                    affected: 50,
                    total: 500,
                })
            })

            try {
                logic = featureFlagReleaseConditionsLogic({
                    id: 'condition-agg-test',
                    filters: {
                        ...generateFeatureFlagFilters([
                            {
                                properties: [
                                    {
                                        key: 'plan',
                                        value: 'pro',
                                        type: PropertyFilterType.Group,
                                        operator: PropertyOperator.Exact,
                                        group_type_index: 1,
                                    },
                                ],
                                rollout_percentage: 100,
                                variant: null,
                                sort_key: 'A',
                                aggregation_group_type_index: 1,
                            },
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        value: 'test',
                                        type: PropertyFilterType.Group,
                                        operator: PropertyOperator.Exact,
                                        group_type_index: 0,
                                    },
                                ],
                                rollout_percentage: 50,
                                variant: null,
                                sort_key: 'B',
                            },
                        ]),
                        aggregation_group_type_index: 0,
                    },
                })

                await expectLogic(logic, () => {
                    logic.mount()
                }).toFinishAllListeners()

                // Condition A has its own aggregation_group_type_index=1, should override flag-level 0
                expect(createSpy).toHaveBeenCalledWith(
                    expect.stringContaining('user_blast_radius'),
                    expect.objectContaining({ group_type_index: 1 })
                )
                // Condition B has no condition-level override, should fall back to flag-level 0
                expect(createSpy).toHaveBeenCalledWith(
                    expect.stringContaining('user_blast_radius'),
                    expect.objectContaining({ group_type_index: 0 })
                )
            } finally {
                createSpy.mockRestore()
            }
        })

        it('stores counts from group-aggregated blast radius response', async () => {
            logic?.unmount()

            const createSpy = jest.spyOn(api, 'create').mockResolvedValue({
                affected: 15,
                total: 80,
            })

            try {
                logic = featureFlagReleaseConditionsLogic({
                    id: 'group-counts-test',
                    filters: {
                        ...generateFeatureFlagFilters([
                            {
                                properties: [
                                    {
                                        key: 'plan',
                                        value: 'pro',
                                        type: PropertyFilterType.Person,
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                                rollout_percentage: 100,
                                variant: null,
                                sort_key: 'A',
                            },
                        ]),
                        aggregation_group_type_index: 0,
                    },
                })

                await expectLogic(logic, () => {
                    logic.mount()
                })
                    .toDispatchActions(['setAffectedCount', 'setTotalCount'])
                    .toFinishAllListeners()

                expect(logic.values.affectedCounts).toEqual({ A: 15 })
                expect(logic.values.totalCounts).toEqual({ A: 80 })
            } finally {
                createSpy.mockRestore()
            }
        })

        describe('API calls', () => {
            it('doesnt make extra API calls when rollout percentage or variants change', async () => {
                logic?.unmount()

                jest.spyOn(api, 'create').mockClear()

                logic = featureFlagReleaseConditionsLogic({
                    id: '12345',
                    filters: generateFeatureFlagFilters([
                        { properties: [], rollout_percentage: undefined, variant: null, sort_key: 'A' },
                        {
                            properties: [
                                {
                                    key: 'aloha',
                                    value: 'aloha',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                            rollout_percentage: undefined,
                            variant: null,
                            sort_key: 'B',
                        },
                        {
                            properties: [
                                {
                                    key: 'aloha',
                                    value: 'aloha2',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                            rollout_percentage: undefined,
                            variant: null,
                            sort_key: 'C',
                        },
                    ]),
                })

                // Mount and wait for all listeners to finish
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()

                // Verify final state - all conditions have their blast radius calculated
                expect(logic.values.affectedCounts).toEqual({ A: 120, B: 120, C: 120 })
                expect(logic.values.totalCounts).toEqual({ A: 2000, B: 2000, C: 2000 })

                // 3 API calls made (one for each condition)
                expect(api.create).toHaveBeenCalledTimes(3)

                // Change rollout percentage and variant - should NOT trigger additional API calls
                logic.actions.updateConditionSet(0, 20, undefined, undefined)
                logic.actions.updateConditionSet(1, 30, undefined, 'test-variant')
                logic.actions.updateConditionSet(2, undefined, undefined, 'test-variant2')
                await expectLogic(logic).toFinishAllListeners()

                // No extra API calls when only changing rollout percentage or variant
                expect(api.create).toHaveBeenCalledTimes(3)
            })
        })
    })

    describe('moving condition sets', () => {
        it('moves simple condition set up', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetUp(1)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'C' },
            ])
        })

        it('moves simple condition set down', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetDown(0)

            expect(logic.values.filters.groups).toEqual([
                { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'C' },
            ])
        })

        it('preserves properties after reordering', () => {
            const filters = generateFeatureFlagFilters([
                {
                    properties: [
                        {
                            key: '$current_url',
                            type: PropertyFilterType.Person,
                            value: 'qa-33-percent-off-yearly-v1',
                            operator: PropertyOperator.IContains,
                        },
                    ],
                    rollout_percentage: 50,
                    variant: null,
                    sort_key: 'A',
                },
                {
                    properties: [
                        {
                            key: 'current_organization_membership_level',
                            type: PropertyFilterType.Person,
                            value: ['15'],
                            operator: PropertyOperator.Exact,
                        },
                        {
                            key: 'email',
                            type: PropertyFilterType.Person,
                            value: ['customer-two@example.com', 'customer-six@example.com'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 75,
                    variant: null,
                    sort_key: 'B',
                },
            ])

            logic.actions.setFilters(filters)

            logic.actions.moveConditionSetUp(1)

            expect(logic.values.filters.groups).toEqual([
                {
                    properties: [
                        {
                            key: 'current_organization_membership_level',
                            type: PropertyFilterType.Person,
                            value: ['15'],
                            operator: PropertyOperator.Exact,
                        },
                        {
                            key: 'email',
                            type: PropertyFilterType.Person,
                            value: ['customer-two@example.com', 'customer-six@example.com'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 75,
                    variant: null,
                    sort_key: 'B',
                },
                {
                    properties: [
                        {
                            key: '$current_url',
                            type: PropertyFilterType.Person,
                            value: 'qa-33-percent-off-yearly-v1',
                            operator: PropertyOperator.IContains,
                        },
                    ],
                    rollout_percentage: 50,
                    variant: null,
                    sort_key: 'A',
                },
            ])
        })
    })

    describe('rollout percentage validation', () => {
        it('validates rollout percentage is defined', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: undefined, variant: null, sort_key: 'A' },
            ])
            logic.actions.setFilters(filters)

            expect(logic.values.propertySelectErrors[0].rollout_percentage).toBe('You need to set a rollout % value')
        })

        it('validates rollout percentage is a valid number', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: NaN, variant: null, sort_key: 'A' },
            ])
            logic.actions.setFilters(filters)

            expect(logic.values.propertySelectErrors[0].rollout_percentage).toBe(
                'Rollout percentage must be a valid number'
            )
        })

        it('validates rollout percentage is within 0-100 range', () => {
            let filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: -10, variant: null, sort_key: 'A' },
            ])
            logic.actions.setFilters(filters)

            expect(logic.values.propertySelectErrors[0].rollout_percentage).toBe(
                'Rollout percentage must be between 0 and 100'
            )

            filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: 150, variant: null, sort_key: 'A' },
            ])
            logic.actions.setFilters(filters)

            expect(logic.values.propertySelectErrors[0].rollout_percentage).toBe(
                'Rollout percentage must be between 0 and 100'
            )
        })

        it.each([
            ['integer boundary values', 0, 50, 100],
            ['decimal sub-1% values', 0.01, 0.15, 33.33],
        ])('accepts valid rollout percentages (%s)', (_label, a, b, c) => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: a, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: b, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: c, variant: null, sort_key: 'C' },
            ])
            logic.actions.setFilters(filters)

            expect(logic.values.propertySelectErrors[0].rollout_percentage).toBeUndefined()
            expect(logic.values.propertySelectErrors[1].rollout_percentage).toBeUndefined()
            expect(logic.values.propertySelectErrors[2].rollout_percentage).toBeUndefined()
        })
    })

    describe('condition set descriptions', () => {
        it('updates description for a condition set', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                {
                    properties: [],
                    rollout_percentage: 75,
                    variant: null,
                    sort_key: 'B',
                    description: 'Initial description',
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.updateConditionSet(0, undefined, undefined, undefined, 'New description for set 1')

            expect(logic.values.filters.groups[0].description).toBe('New description for set 1')
            expect(logic.values.filters.groups[1].description).toBe('Initial description')
        })

        it('clears description when set to empty string', () => {
            const filters = generateFeatureFlagFilters([
                {
                    properties: [],
                    rollout_percentage: 50,
                    variant: null,
                    sort_key: 'A',
                    description: 'Existing description',
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.updateConditionSet(0, undefined, undefined, undefined, '')

            expect(logic.values.filters.groups[0].description).toBe(null)
        })

        it('preserves description when updating other properties', () => {
            const filters = generateFeatureFlagFilters([
                {
                    properties: [],
                    rollout_percentage: 50,
                    variant: null,
                    sort_key: 'A',
                    description: 'My test condition',
                },
            ])
            logic.actions.setFilters(filters)

            logic.actions.updateConditionSet(0, 75)
            expect(logic.values.filters.groups[0].description).toBe('My test condition')
            expect(logic.values.filters.groups[0].rollout_percentage).toBe(75)

            logic.actions.updateConditionSet(0, undefined, undefined, 'variant-a')
            expect(logic.values.filters.groups[0].description).toBe('My test condition')
            expect(logic.values.filters.groups[0].variant).toBe('variant-a')

            logic.actions.updateConditionSet(0, undefined, [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    value: 'test@example.com',
                    operator: PropertyOperator.Exact,
                },
            ])
            expect(logic.values.filters.groups[0].description).toBe('My test condition')
            expect(logic.values.filters.groups[0].properties).toHaveLength(1)
        })
    })

    describe('open conditions state', () => {
        it('initializes first condition as open when there is only one group', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-1',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            }).toMatchValues({
                openConditions: ['condition-A'],
            })
        })

        it('does not auto-open conditions when there are multiple groups', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-2',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                    { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            }).toMatchValues({
                openConditions: [],
            })
        })

        it('opens new condition when adding a condition set', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-3',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                ]),
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.addConditionSet('NEW-KEY')
            }).toMatchValues({
                openConditions: ['condition-A', 'condition-NEW-KEY'],
            })
        })

        it('opens duplicated condition when duplicating a condition set', async () => {
            logic?.unmount()

            nextUuid = 'DUP'
            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-4',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                ]),
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.duplicateConditionSet(0)
            }).toMatchValues({
                openConditions: ['condition-A', 'condition-DUP'],
            })
        })

        it('removes condition from openConditions when removing a condition set', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-5',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'A' },
                    { properties: [], rollout_percentage: 75, variant: null, sort_key: 'B' },
                ]),
            })
            logic.mount()

            // Manually open both conditions and wait for it to be processed
            await expectLogic(logic, () => {
                logic.actions.setOpenConditions(['condition-A', 'condition-B'])
            }).toMatchValues({
                openConditions: ['condition-A', 'condition-B'],
            })

            // Now remove condition A and verify B remains open
            await expectLogic(logic, () => {
                logic.actions.removeConditionSet(0)
            })
                .toDispatchActions(['removeConditionSet', 'setOpenConditions'])
                .toMatchValues({
                    openConditions: ['condition-B'],
                })
        })

        it('preserves open state by index when changing aggregation type', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'open-test-6',
                filters: {
                    ...generateFeatureFlagFilters([
                        { properties: [], rollout_percentage: 50, variant: null, sort_key: 'OLD-KEY' },
                    ]),
                    aggregation_group_type_index: null,
                },
            })

            // Mount and wait for initial setOpenConditions
            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['setOpenConditions'])
                .toMatchValues({
                    openConditions: ['condition-OLD-KEY'],
                })

            // Switch to group aggregation - direct user→group resets groups with new sort_key
            nextUuid = 'NEW-KEY'
            await expectLogic(logic, () => {
                logic.actions.setAggregationGroupTypeIndex(0)
            })
                .toDispatchActions(['setAggregationGroupTypeIndex', 'setOpenConditions'])
                .toMatchValues({
                    openConditions: ['condition-NEW-KEY'],
                })
        })

        it('can reorder condition sets', async () => {
            logic?.unmount()

            // Create logic with multiple condition sets
            logic = featureFlagReleaseConditionsLogic({
                id: 'reorder-test',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'first' },
                    { properties: [], rollout_percentage: 30, variant: null, sort_key: 'second' },
                    { properties: [], rollout_percentage: 20, variant: null, sort_key: 'third' },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            }).toMatchValues({
                filterGroups: [
                    expect.objectContaining({ sort_key: 'first', rollout_percentage: 50 }),
                    expect.objectContaining({ sort_key: 'second', rollout_percentage: 30 }),
                    expect.objectContaining({ sort_key: 'third', rollout_percentage: 20 }),
                ],
            })

            // Reorder: move 'first' to after 'second'
            await expectLogic(logic, () => {
                logic.actions.reorderConditionSets('first', 'second')
            }).toMatchValues({
                filterGroups: [
                    expect.objectContaining({ sort_key: 'second', rollout_percentage: 30 }),
                    expect.objectContaining({ sort_key: 'first', rollout_percentage: 50 }),
                    expect.objectContaining({ sort_key: 'third', rollout_percentage: 20 }),
                ],
            })

            // Reorder: move 'third' to the beginning
            await expectLogic(logic, () => {
                logic.actions.reorderConditionSets('third', 'second')
            }).toMatchValues({
                filterGroups: [
                    expect.objectContaining({ sort_key: 'third', rollout_percentage: 20 }),
                    expect.objectContaining({ sort_key: 'second', rollout_percentage: 30 }),
                    expect.objectContaining({ sort_key: 'first', rollout_percentage: 50 }),
                ],
            })
        })

        it('ignores reorder when activeId equals overId', async () => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: 'reorder-same-test',
                filters: generateFeatureFlagFilters([
                    { properties: [], rollout_percentage: 50, variant: null, sort_key: 'first' },
                    { properties: [], rollout_percentage: 30, variant: null, sort_key: 'second' },
                ]),
            })

            await expectLogic(logic, () => {
                logic.mount()
            }).toMatchValues({
                filterGroups: [
                    expect.objectContaining({ sort_key: 'first', rollout_percentage: 50 }),
                    expect.objectContaining({ sort_key: 'second', rollout_percentage: 30 }),
                ],
            })

            // Try to reorder same item to itself - should be ignored
            await expectLogic(logic, () => {
                logic.actions.reorderConditionSets('first', 'first')
            }).toMatchValues({
                // Should remain unchanged
                filterGroups: [
                    expect.objectContaining({ sort_key: 'first', rollout_percentage: 50 }),
                    expect.objectContaining({ sort_key: 'second', rollout_percentage: 30 }),
                ],
            })
        })
    })

    describe('targeting mode transitions', () => {
        const userProperties: AnyPropertyFilter[] = [
            {
                key: 'email',
                value: ['test@posthog.com'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Person,
            },
        ]

        const groupProperties: AnyPropertyFilter[] = [
            {
                key: 'industry',
                value: ['tech'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Group,
            },
        ]

        it('fully resets conditions when switching between incompatible types (user to group)', async () => {
            logic?.unmount()

            nextUuid = 'RESET'
            logic = featureFlagReleaseConditionsLogic({
                id: 'transition-user-to-group',
                filters: {
                    ...generateFeatureFlagFilters([
                        {
                            properties: userProperties,
                            rollout_percentage: 50,
                            variant: 'control',
                            sort_key: 'cond-1',
                            description: 'Beta users',
                        },
                        {
                            properties: userProperties,
                            rollout_percentage: 30,
                            variant: 'test',
                            sort_key: 'cond-2',
                            description: 'Alpha users',
                        },
                    ]),
                    aggregation_group_type_index: null,
                },
            })

            await expectLogic(logic, () => {
                logic.mount()
            })

            // Direct user→group transition resets to a single empty condition
            nextUuid = 'NEW'
            await expectLogic(logic, () => {
                logic.actions.setAggregationGroupTypeIndex(0)
            }).toMatchValues({
                filters: expect.objectContaining({
                    aggregation_group_type_index: 0,
                    groups: [
                        expect.objectContaining({
                            sort_key: 'NEW',
                            rollout_percentage: 50, // Preserves first condition's rollout %
                            variant: null,
                            properties: [],
                        }),
                    ],
                }),
            })
        })

        it.each([
            {
                name: 'group → mixed',
                initialGlobal: 0 as number | null,
                initialGroups: [
                    {
                        properties: groupProperties,
                        rollout_percentage: 50,
                        variant: 'control' as string | null,
                        sort_key: 'cond-1',
                        description: 'Tech orgs',
                    },
                    {
                        properties: groupProperties,
                        rollout_percentage: 100,
                        variant: null as string | null,
                        sort_key: 'cond-2',
                        description: 'All orgs',
                    },
                ],
                expectedPerConditionAgg: 0 as number | null,
            },
            {
                name: 'user → mixed',
                initialGlobal: null,
                initialGroups: [
                    {
                        properties: userProperties,
                        rollout_percentage: 75,
                        variant: null as string | null,
                        sort_key: 'cond-1',
                    },
                ],
                expectedPerConditionAgg: null,
            },
        ])(
            'preserves everything when switching $name',
            async ({ initialGlobal, initialGroups, expectedPerConditionAgg }) => {
                logic?.unmount()

                logic = featureFlagReleaseConditionsLogic({
                    id: `transition-to-mixed`,
                    filters: {
                        ...generateFeatureFlagFilters(initialGroups),
                        aggregation_group_type_index: initialGlobal,
                    },
                })

                await expectLogic(logic, () => {
                    logic.mount()
                })

                await expectLogic(logic, () => {
                    logic.actions.switchToMixedTargeting()
                }).toMatchValues({
                    isMixedTargeting: true,
                    filters: expect.objectContaining({
                        aggregation_group_type_index: null,
                        groups: initialGroups.map((g) =>
                            expect.objectContaining({
                                ...g,
                                aggregation_group_type_index: expectedPerConditionAgg,
                            })
                        ),
                    }),
                })
            }
        )

        it.each([
            {
                name: 'mixed → user',
                targetAggregation: null as number | null,
                expectedGroups: [
                    { sort_key: 'user-cond', rollout_percentage: 50, properties: userProperties },
                    { sort_key: 'group-cond', rollout_percentage: 30, variant: 'test', properties: [] },
                ],
            },
            {
                name: 'mixed → group',
                targetAggregation: 0 as number | null,
                expectedGroups: [
                    { sort_key: 'user-cond', rollout_percentage: 50, properties: [] },
                    { sort_key: 'group-cond', rollout_percentage: 30, properties: groupProperties },
                ],
            },
        ])('selectively clears properties when switching $name', async ({ targetAggregation, expectedGroups }) => {
            logic?.unmount()

            logic = featureFlagReleaseConditionsLogic({
                id: `transition-from-mixed`,
                filters: {
                    ...generateFeatureFlagFilters([
                        {
                            properties: userProperties,
                            rollout_percentage: 50,
                            variant: null,
                            sort_key: 'user-cond',
                            aggregation_group_type_index: null,
                        },
                        {
                            properties: groupProperties,
                            rollout_percentage: 30,
                            variant: 'test',
                            sort_key: 'group-cond',
                            aggregation_group_type_index: 0,
                        },
                    ]),
                    aggregation_group_type_index: null,
                },
            })

            await expectLogic(logic, () => {
                logic.mount()
            })

            await expectLogic(logic, () => {
                logic.actions.setAggregationGroupTypeIndex(targetAggregation)
            }).toMatchValues({
                filters: expect.objectContaining({
                    aggregation_group_type_index: targetAggregation,
                    groups: expectedGroups.map((g) => expect.objectContaining(g)),
                }),
            })
        })
    })
})
