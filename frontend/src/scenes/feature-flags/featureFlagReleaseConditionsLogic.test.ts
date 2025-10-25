import { expectLogic } from 'kea-test-utils'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
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
                    variant: null,
                },
            ]),
        })
        logic.mount()

        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [
                    200,
                    { users_affected: 120, total_users: 2000 },
                ],
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
                .toDispatchActions(['calculateBlastRadius', 'setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 120 },
                    totalUsers: 2000,
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
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 140, total_users: 2000 }))
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 240, total_users: 2002 }))
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 500, total_users: 2000 }))
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 750, total_users: 2001 }))

                logic.mount()
            })
                .toDispatchActions(['setAffectedUsers', 'setAffectedUsers', 'setAffectedUsers', 'setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: undefined, B: undefined, C: undefined, D: undefined },
                    totalUsers: null,
                })
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: 140, B: undefined, C: undefined, D: undefined },
                    totalUsers: null,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 140, B: 240 },
                    totalUsers: 2002,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 140, B: 240, C: 500 },
                    totalUsers: 2000,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 140, B: 240, C: 500, D: 750 },
                    totalUsers: 2001,
                })
        })

        it('updates when adding conditions to a flag', async () => {
            jest.spyOn(api, 'create')
                .mockReturnValueOnce(Promise.resolve({ users_affected: 124, total_users: 2000 }))
                .mockReturnValueOnce(Promise.resolve({ users_affected: 248, total_users: 2000 }))
                .mockReturnValueOnce(Promise.resolve({ users_affected: 496, total_users: 2000 }))

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
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(0, 20, [
                    {
                        key: 'aloha',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: null,
                    },
                ])
            })
                // first call is to clear the affected users on mount
                // second call is to set the affected users for mount logic conditions
                // third call is to set the affected users for the updateConditionSet action
                .toDispatchActions(['setAffectedUsers', 'setAffectedUsers', 'setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 124 },
                    totalUsers: 2000,
                })

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
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: undefined },
                    totalUsers: 2000,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 248 },
                    totalUsers: 2000,
                })

            // Add another condition set
            await expectLogic(logic, () => {
                nextUuid = 'B'
                logic.actions.addConditionSet()
            })
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    // expect the new empty condition set to initialize affected users to be same as total users
                    affectedUsers: { A: 248, B: 2000 },
                    totalUsers: 2000,
                })
                .toNotHaveDispatchedActions(['setTotalUsers'])

            // update newly added condition set
            await expectLogic(logic, () => {
                logic.actions.updateConditionSet(1, 20, [
                    {
                        key: 'aloha',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: null,
                    },
                ])
            })
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: 248, B: undefined },
                    totalUsers: 2000,
                })
                .toNotHaveDispatchedActions(['setTotalUsers'])

            // select its value
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
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: 248, B: undefined },
                    totalUsers: 2000,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { A: 248, B: 496 },
                    totalUsers: 2000,
                })

            // Remove a condition set
            await expectLogic(logic, () => {
                logic.actions.removeConditionSet(0)
            })
                .toNotHaveDispatchedActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { A: 248, B: 496 },
                })
        })

        it('computes blast radius percentages accurately', async () => {
            logic.actions.setAffectedUsers('A', 100)
            logic.actions.setAffectedUsers('B', 200)
            logic.actions.setAffectedUsers('C', 346)
            logic.actions.setTotalUsers(1000)

            expect(logic.values.computeBlastRadiusPercentage(20, 'A')).toBeCloseTo(2, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 'A')).toBeCloseTo(3.3, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 'B')).toBeCloseTo(10, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 'B')).toBeCloseTo(20, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(34.6, 2)
            expect(logic.values.computeBlastRadiusPercentage(67, 'C')).toBeCloseTo(23.182, 2)
        })

        it('computes blast radius percentages accurately with missing information', async () => {
            logic.actions.setAffectedUsers('A', -1)
            logic.actions.setAffectedUsers('B', undefined)
            logic.actions.setAffectedUsers('C', 25)
            // total users is null as well

            expect(logic.values.computeBlastRadiusPercentage(20, 'A')).toBeCloseTo(20, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 'A')).toBeCloseTo(33, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 'B')).toBeCloseTo(50, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 'B')).toBeCloseTo(100, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(100, 2)
            expect(logic.values.computeBlastRadiusPercentage(10, 'C')).toBeCloseTo(10, 2)

            logic.actions.setTotalUsers(100)
            expect(logic.values.computeBlastRadiusPercentage(67, 'A')).toBeCloseTo(67, 2)
            // total users is defined but affected users is not. UI side should handle not showing the result in this case
            // and computation resolves to rollout percentage
            expect(logic.values.computeBlastRadiusPercentage(75, 'B')).toEqual(75)
            expect(logic.values.computeBlastRadiusPercentage(100, 'C')).toBeCloseTo(25, 2)

            logic.actions.setTotalUsers(500_000_000)
            logic.actions.setAffectedUsers('A', 249_999_000)
            expect(logic.values.computeBlastRadiusPercentage(100, 'A')).toEqual(49.9998)
            expect(logic.values.computeBlastRadiusPercentage(5, 'C')).toEqual(0)
        })

        describe('API calls', () => {
            beforeEach(() => {
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
                logic.mount()
            })

            it('doesnt make extra API calls when rollout percentage or variants change', async () => {
                await expectLogic(logic)
                    .toDispatchActions([
                        'setAffectedUsers',
                        'setAffectedUsers',
                        'setAffectedUsers',
                        'setAffectedUsers',
                        'setAffectedUsers',
                        'setAffectedUsers',
                        'setTotalUsers',
                    ])
                    .toMatchValues({
                        affectedUsers: { A: 120, B: 120, C: 120 },
                        totalUsers: 2000,
                    })

                expect(api.create).toHaveBeenCalledTimes(3)

                await expectLogic(logic, () => {
                    logic.actions.updateConditionSet(0, 20, undefined, undefined)
                }).toNotHaveDispatchedActions(['setAffectedUsers', 'setTotalUsers'])

                await expectLogic(logic, () => {
                    logic.actions.updateConditionSet(1, 30, undefined, 'test-variant')
                }).toNotHaveDispatchedActions(['setAffectedUsers', 'setTotalUsers'])

                await expectLogic(logic, () => {
                    logic.actions.updateConditionSet(2, undefined, undefined, 'test-variant2')
                }).toNotHaveDispatchedActions(['setAffectedUsers', 'setTotalUsers'])

                // no extra calls when changing rollout percentage
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

        it('accepts valid rollout percentages', () => {
            const filters = generateFeatureFlagFilters([
                { properties: [], rollout_percentage: 0, variant: null, sort_key: 'A' },
                { properties: [], rollout_percentage: 50, variant: null, sort_key: 'B' },
                { properties: [], rollout_percentage: 100, variant: null, sort_key: 'C' },
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
})
