import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    FeatureFlagGroupType,
    FeatureFlagType,
    MultivariateFlagOptions,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

function generateFeatureFlag(
    groups: FeatureFlagGroupType[],
    multivariate?: MultivariateFlagOptions,
    id: number | null = 123,
    has_enriched_analytics?: boolean
): FeatureFlagType {
    return {
        id,
        created_at: null,
        key: 'beta-feature',
        name: 'Beta Feature',
        filters: { groups, multivariate: multivariate ?? null, payloads: {} },
        deleted: false,
        active: true,
        created_by: null,
        is_simple_flag: false,
        rollout_percentage: 0,
        ensure_experience_continuity: false,
        experiment_set: null,
        features: [],
        rollback_conditions: [],
        performed_rollback: false,
        can_edit: true,
        usage_dashboard: 1234,
        tags: [],
        has_enriched_analytics,
        surveys: [],
    }
}

describe('the feature flag logic', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagLogic()
        logic.mount()

        useMocks({
            get: {
                'api/sentry_stats/': { total_count: 3, sentry_integration_enabled: true },
            },
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
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(
                    generateFeatureFlag([
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
                        },
                    ])
                )
                logic.actions.editFeatureFlag(true)
            })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: 120 },
                    totalUsers: 2000,
                })
        })

        it('loads when editing a flag with multiple conditions', async () => {
            await expectLogic(logic, () => {
                jest.spyOn(api, 'create')
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 140, total_users: 2000 }))
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 240, total_users: 2002 }))
                    .mockReturnValueOnce(Promise.resolve({ users_affected: 500, total_users: 2000 }))

                logic.actions.setFeatureFlag(
                    generateFeatureFlag([
                        { properties: [], rollout_percentage: 86, variant: null },
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
                        },
                    ])
                )
                logic.actions.editFeatureFlag(true)
            })
                .toDispatchActions(['setAffectedUsers', 'setAffectedUsers', 'setAffectedUsers', 'setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { 0: undefined, 1: undefined, 2: undefined, 3: undefined },
                    totalUsers: null,
                })
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { 0: -1, 1: undefined, 2: undefined, 3: undefined },
                    totalUsers: null,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: -1, 1: 140 },
                    totalUsers: 2000,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: -1, 1: 140, 2: 240 },
                    totalUsers: 2002,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: -1, 1: 140, 2: 240, 3: 500 },
                    totalUsers: 2000,
                })
        })

        it('loads when creating a new flag', async () => {
            jest.spyOn(api, 'create')
            await expectLogic(logic, () => {
                logic.actions.resetFeatureFlag()
            }).toMatchValues({
                affectedUsers: { 0: -1 },
                totalUsers: null,
            })

            expect(api.create).not.toHaveBeenCalled()
        })

        it('updates when adding conditions to a flag', async () => {
            jest.spyOn(api, 'create')
                .mockReturnValueOnce(Promise.resolve({ users_affected: 140, total_users: 2000 }))
                .mockReturnValueOnce(Promise.resolve({ users_affected: 240, total_users: 2000 }))

            await expectLogic(logic, () => {
                logic.actions.resetFeatureFlag()
            }).toMatchValues({
                affectedUsers: { 0: -1 },
                totalUsers: null,
            })

            expect(api.create).not.toHaveBeenCalled()

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
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { 0: undefined },
                    totalUsers: null,
                })
                .toNotHaveDispatchedActions(['setTotalUsers'])

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
                    affectedUsers: { 0: undefined },
                    totalUsers: null,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: 140 },
                    totalUsers: 2000,
                })

            // Add another condition set
            await expectLogic(logic, () => {
                logic.actions.addConditionSet()
            })
                .toDispatchActions(['setAffectedUsers'])
                .toMatchValues({
                    affectedUsers: { 0: 140, 1: -1 },
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
                    affectedUsers: { 0: 140, 1: undefined },
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
                    affectedUsers: { 0: 140, 1: undefined },
                    totalUsers: 2000,
                })
                .toDispatchActions(['setAffectedUsers', 'setTotalUsers'])
                .toMatchValues({
                    affectedUsers: { 0: 140, 1: 240 },
                    totalUsers: 2000,
                })
        })

        it('computes blast radius percentages accurately', async () => {
            logic.actions.setAffectedUsers(0, 100)
            logic.actions.setAffectedUsers(1, 200)
            logic.actions.setAffectedUsers(2, 346)
            logic.actions.setTotalUsers(1000)

            expect(logic.values.computeBlastRadiusPercentage(20, 0)).toBeCloseTo(2, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 0)).toBeCloseTo(3.3, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 1)).toBeCloseTo(10, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 1)).toBeCloseTo(20, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBeCloseTo(34.6, 2)
            expect(logic.values.computeBlastRadiusPercentage(67, 2)).toBeCloseTo(23.182, 2)
        })

        it('computes blast radius percentages accurately with missing information', async () => {
            logic.actions.setAffectedUsers(0, -1)
            logic.actions.setAffectedUsers(1, undefined)
            logic.actions.setAffectedUsers(2, 25)
            // total users is null as well

            expect(logic.values.computeBlastRadiusPercentage(20, 0)).toBeCloseTo(20, 2)
            expect(logic.values.computeBlastRadiusPercentage(33, 0)).toBeCloseTo(33, 2)

            expect(logic.values.computeBlastRadiusPercentage(50, 1)).toBeCloseTo(50, 2)
            expect(logic.values.computeBlastRadiusPercentage(100, 1)).toBeCloseTo(100, 2)

            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBeCloseTo(100, 2)
            expect(logic.values.computeBlastRadiusPercentage(10, 2)).toBeCloseTo(10, 2)

            logic.actions.setTotalUsers(100)
            expect(logic.values.computeBlastRadiusPercentage(67, 0)).toBeCloseTo(67, 2)
            // total users is defined but affected users is not. UI side should handle not showing the result in this case
            // and computation resolves to rollout percentage
            expect(logic.values.computeBlastRadiusPercentage(75, 1)).toEqual(75)
            expect(logic.values.computeBlastRadiusPercentage(100, 2)).toBeCloseTo(25, 2)
        })

        it('doesnt make extra API calls when rollout percentage or variants change', async () => {
            jest.spyOn(api, 'create')
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(
                    generateFeatureFlag([
                        { properties: [], rollout_percentage: undefined, variant: null },
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
                        },
                    ])
                )
                logic.actions.editFeatureFlag(true)
            })
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
                    affectedUsers: { 0: -1, 1: 120, 2: 120 },
                    totalUsers: 2000,
                })

            expect(api.create).toHaveBeenCalledTimes(2)

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
            expect(api.create).toHaveBeenCalledTimes(2)
        })
    })
})
