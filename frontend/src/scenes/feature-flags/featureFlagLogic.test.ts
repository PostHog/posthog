import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { detectFeatureFlagChanges } from './featureFlagConfirmationLogic'
import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'

const MOCK_FEATURE_FLAG = {
    ...NEW_FLAG,
    id: 1,
    key: 'test-flag',
    name: 'test-name',
}

const MOCK_FEATURE_FLAG_STATUS = {
    status: 'active',
    reason: 'mock reason',
}

const MOCK_EXPERIMENT = {
    id: 123,
    name: 'Test Experiment',
    feature_flag_key: 'test-flag',
    start_date: '2023-01-01',
}

const MOCK_DEPENDENT_FLAGS = [
    { id: 10, key: 'dependent-flag-1', name: 'Dependent Flag 1' },
    { id: 11, key: 'dependent-flag-2', name: 'Dependent Flag 2' },
]

describe('featureFlagLogic', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = featureFlagLogic({ id: 1 })
        logic.mount()

        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${MOCK_FEATURE_FLAG.id}/`]: () => [
                    200,
                    MOCK_FEATURE_FLAG,
                ],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${MOCK_FEATURE_FLAG.id}/status`]: () => [
                    200,
                    MOCK_FEATURE_FLAG_STATUS,
                ],
            },
        })

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('setMultivariateEnabled functionality', () => {
        it('adds an empty variant when enabling multivariate', async () => {
            await expectLogic(logic).toMatchValues({
                featureFlag: partial({
                    filters: partial({
                        groups: [
                            {
                                properties: [],
                                variant: null,
                            },
                        ],
                    }),
                }),
                variants: [],
            })
            await expectLogic(logic, () => {
                logic.actions.setMultivariateEnabled(true)
            })
                .toDispatchActions(['setMultivariateEnabled', 'setMultivariateOptions'])
                .toMatchValues({
                    variants: [
                        {
                            key: '',
                            name: '',
                            rollout_percentage: 100,
                        },
                    ],
                })
        })

        it('resets the variants and group variant keys when disabling multivariate', async () => {
            const MOCK_MULTIVARIATE_FEATURE_FLAG: FeatureFlagType = {
                ...logic.values.featureFlag,
                filters: {
                    groups: [
                        {
                            variant: 'control1',
                            properties: [
                                {
                                    key: '$browser',
                                    type: PropertyFilterType.Person,
                                    value: 'Chrome',
                                    operator: PropertyOperator.Regex,
                                },
                            ],
                            rollout_percentage: 100,
                        },
                    ],
                    payloads: {
                        control1: '{"key": "value"}',
                    },
                    multivariate: {
                        variants: [
                            {
                                key: 'control1',
                                name: 'Control 1',
                                rollout_percentage: 30,
                            },
                            {
                                key: 'control2',
                                name: 'Control 2',
                                rollout_percentage: 70,
                            },
                        ],
                    },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(MOCK_MULTIVARIATE_FEATURE_FLAG)
            })
                .toDispatchActions(['setFeatureFlag'])
                .toMatchValues({
                    featureFlag: MOCK_MULTIVARIATE_FEATURE_FLAG,
                })

            await expectLogic(logic, () => {
                logic.actions.setMultivariateEnabled(false)
            })
                .toDispatchActions(['setMultivariateEnabled', 'setMultivariateOptions'])
                .toMatchValues({
                    featureFlag: partial({
                        filters: partial({
                            groups: [
                                {
                                    ...MOCK_MULTIVARIATE_FEATURE_FLAG.filters.groups[0],
                                    variant: null,
                                },
                            ],
                            payloads: {},
                        }),
                    }),
                    variants: [],
                })
        })
    })

    describe('change detection', () => {
        it('detects active status changes', () => {
            const originalFlag = { ...MOCK_FEATURE_FLAG, active: false }
            const changedFlag = { ...originalFlag, active: true }

            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes).toContain('Enable the feature flag')
        })

        it('detects rollout percentage changes', () => {
            const originalFlag = {
                ...MOCK_FEATURE_FLAG,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                },
            }
            const changedFlag = {
                ...originalFlag,
                filters: {
                    groups: [{ properties: [], rollout_percentage: 50, variant: null }],
                },
            }

            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes).toContain('Release condition rollout percentage changed')
        })

        it('returns no changes for new flags', () => {
            const newFlag = { ...NEW_FLAG, key: 'new-flag', name: 'New Flag' }
            const changes = detectFeatureFlagChanges(null, newFlag)
            expect(changes.length).toBe(0)
        })

        it('returns no changes when nothing meaningful changed', () => {
            const originalFlag = MOCK_FEATURE_FLAG
            const changedFlag = { ...originalFlag, name: 'Different Name' } // Name change doesn't trigger confirmation

            const changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            expect(changes.length).toBe(0)
        })
    })

    describe('experiment loading', () => {
        it('loads experiment data when feature flag has an experiment linked', async () => {
            const flagWithExperiment = {
                ...MOCK_FEATURE_FLAG,
                id: 2,
                experiment_set: [MOCK_EXPERIMENT.id],
            }

            const experimentLogic = featureFlagLogic({ id: 2 })
            experimentLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithExperiment.id}/`]: () => [
                        200,
                        flagWithExperiment,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithExperiment.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/experiments/${MOCK_EXPERIMENT.id}/`]: () => [
                        200,
                        MOCK_EXPERIMENT,
                    ],
                },
            })

            await expectLogic(experimentLogic, () => {
                experimentLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadExperimentSuccess'])
                .toMatchValues({
                    featureFlag: partial({
                        id: flagWithExperiment.id,
                        experiment_set: [MOCK_EXPERIMENT.id],
                    }),
                    experiment: MOCK_EXPERIMENT,
                })

            experimentLogic.unmount()
        })

        it('does not load experiment data when feature flag has no experiment', async () => {
            const flagWithoutExperiment = {
                ...MOCK_FEATURE_FLAG,
                id: 3,
                experiment_set: null,
            }

            const noExperimentLogic = featureFlagLogic({ id: 3 })
            noExperimentLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithoutExperiment.id}/`]: () => [
                        200,
                        flagWithoutExperiment,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithoutExperiment.id}/status`]:
                        () => [200, MOCK_FEATURE_FLAG_STATUS],
                },
            })

            await expectLogic(noExperimentLogic, () => {
                noExperimentLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess'])
                .toNotHaveDispatchedActions(['loadExperimentSuccess'])
                .toMatchValues({
                    featureFlag: partial({
                        id: flagWithoutExperiment.id,
                        experiment_set: null,
                    }),
                    experiment: null,
                })

            noExperimentLogic.unmount()
        })
    })

    describe('dependent flags loading', () => {
        it('loads dependent flags when feature flag loads successfully', async () => {
            const flagWithDependents = {
                ...MOCK_FEATURE_FLAG,
                id: 4,
            }

            const dependentFlagsLogic = featureFlagLogic({ id: 4 })
            dependentFlagsLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithDependents.id}/`]: () => [
                        200,
                        flagWithDependents,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithDependents.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                },
                post: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithDependents.id}/has_active_dependents/`]:
                        () => [
                            200,
                            {
                                has_active_dependents: true,
                                dependent_flags: MOCK_DEPENDENT_FLAGS,
                            },
                        ],
                },
            })

            await expectLogic(dependentFlagsLogic, () => {
                dependentFlagsLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsSuccess'])
                .toMatchValues({
                    dependentFlags: MOCK_DEPENDENT_FLAGS,
                })

            dependentFlagsLogic.unmount()
        })

        it('returns empty array when no dependent flags exist', async () => {
            const flagWithoutDependents = {
                ...MOCK_FEATURE_FLAG,
                id: 5,
            }

            const noDependentsLogic = featureFlagLogic({ id: 5 })
            noDependentsLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithoutDependents.id}/`]: () => [
                        200,
                        flagWithoutDependents,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithoutDependents.id}/status`]:
                        () => [200, MOCK_FEATURE_FLAG_STATUS],
                },
                post: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithoutDependents.id}/has_active_dependents/`]:
                        () => [
                            200,
                            {
                                has_active_dependents: false,
                                dependent_flags: [],
                            },
                        ],
                },
            })

            await expectLogic(noDependentsLogic, () => {
                noDependentsLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsSuccess'])
                .toMatchValues({
                    dependentFlags: [],
                })

            noDependentsLogic.unmount()
        })

        it('handles API failure gracefully and returns empty array', async () => {
            const flagWithError = {
                ...MOCK_FEATURE_FLAG,
                id: 14,
            }

            const errorLogic = featureFlagLogic({ id: 14 })
            errorLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithError.id}/`]: () => [
                        200,
                        flagWithError,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithError.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                },
                post: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flagWithError.id}/has_active_dependents/`]:
                        () => [500, { error: 'Internal server error' }],
                },
            })

            await expectLogic(errorLogic, () => {
                errorLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsFailure'])
                .toMatchValues({
                    dependentFlags: [],
                    dependentFlagsLoading: false,
                })

            errorLogic.unmount()
        })
    })
})
