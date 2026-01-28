import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { mergeTemplateValues } from './FeatureFlagTemplates'
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
        jest.useRealTimers()
    })

    describe('setMultivariateEnabled functionality', () => {
        it('adds default variants when enabling multivariate', async () => {
            await expectLogic(logic).toMatchValues({
                featureFlag: partial({
                    filters: partial({
                        groups: [
                            partial({
                                properties: [],
                                variant: null,
                            }),
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
                            key: 'control',
                            name: '',
                            rollout_percentage: 50,
                        },
                        {
                            key: 'test',
                            name: '',
                            rollout_percentage: 50,
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

    describe('dependent flags confirmation', () => {
        it('uses pre-loaded dependent flags when data is available', async () => {
            const flag = { ...MOCK_FEATURE_FLAG, id: 6, active: true }

            const testLogic = featureFlagLogic({ id: 6 })
            testLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/`]: () => [200, flag],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/dependent_flags/`]: () => [
                        200,
                        MOCK_DEPENDENT_FLAGS,
                    ],
                },
            })

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            }).toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlagsSuccess'])

            expect(testLogic.values.dependentFlags).toEqual(MOCK_DEPENDENT_FLAGS)
            expect(testLogic.values.dependentFlagsLoading).toBe(false)

            testLogic.unmount()
        })
    })

    describe('dependent flags loading', () => {
        it('loads dependent flags when feature flag loads successfully', async () => {
            const flag = { ...MOCK_FEATURE_FLAG, id: 4 }

            const testLogic = featureFlagLogic({ id: 4 })
            testLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/`]: () => [200, flag],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/dependent_flags/`]: () => [
                        200,
                        MOCK_DEPENDENT_FLAGS,
                    ],
                },
            })

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsSuccess'])
                .toMatchValues({ dependentFlags: MOCK_DEPENDENT_FLAGS })

            testLogic.unmount()
        })

        it('returns empty array when no dependent flags exist', async () => {
            const flag = { ...MOCK_FEATURE_FLAG, id: 5 }

            const testLogic = featureFlagLogic({ id: 5 })
            testLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/`]: () => [200, flag],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/dependent_flags/`]: () => [
                        200,
                        [],
                    ],
                },
            })

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsSuccess'])
                .toMatchValues({ dependentFlags: [] })

            testLogic.unmount()
        })

        it('handles API failure gracefully and returns empty array', async () => {
            const flag = { ...MOCK_FEATURE_FLAG, id: 14 }

            const testLogic = featureFlagLogic({ id: 14 })
            testLogic.mount()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/`]: () => [200, flag],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/status`]: () => [
                        200,
                        MOCK_FEATURE_FLAG_STATUS,
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/${flag.id}/dependent_flags/`]: () => [
                        500,
                        { error: 'Internal server error' },
                    ],
                },
            })

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsFailure'])
                .toMatchValues({ dependentFlags: [], dependentFlagsLoading: false })

            testLogic.unmount()
        })
    })

    describe('userEditedFields tracking', () => {
        it('tracks fields marked as edited', async () => {
            await expectLogic(logic).toMatchValues({
                userEditedFields: new Set(),
            })

            await expectLogic(logic, () => {
                logic.actions.markFieldAsEdited('key')
            }).toMatchValues({
                userEditedFields: new Set(['key']),
            })

            await expectLogic(logic, () => {
                logic.actions.markFieldAsEdited('filters')
            }).toMatchValues({
                userEditedFields: new Set(['key', 'filters']),
            })
        })

        it('does not duplicate fields when marked multiple times', async () => {
            await expectLogic(logic, () => {
                logic.actions.markFieldAsEdited('key')
                logic.actions.markFieldAsEdited('key')
            }).toMatchValues({
                userEditedFields: new Set(['key']),
            })
        })

        it('resets edited fields', async () => {
            await expectLogic(logic, () => {
                logic.actions.markFieldAsEdited('key')
                logic.actions.markFieldAsEdited('name')
            }).toMatchValues({
                userEditedFields: new Set(['key', 'name']),
            })

            await expectLogic(logic, () => {
                logic.actions.resetEditedFields()
            }).toMatchValues({
                userEditedFields: new Set(),
            })
        })
    })
})

describe('mergeTemplateValues', () => {
    const baseFlag = {
        ...NEW_FLAG,
        id: 1,
        key: '',
        name: '',
        active: false,
    } as unknown as FeatureFlagType

    it('applies all template values when no fields are edited', () => {
        const templateValues = {
            key: 'gradual-rollout',
            name: 'Gradual rollout flag',
            active: true,
            filters: { groups: [{ properties: [], rollout_percentage: 20, variant: null }] },
        }

        const result = mergeTemplateValues(baseFlag, templateValues, new Set())

        expect(result.updatedFlag.key).toBe('gradual-rollout')
        expect(result.updatedFlag.name).toBe('Gradual rollout flag')
        expect(result.updatedFlag.active).toBe(true)
        expect(result.updatedFlag.filters?.groups).toEqual([{ properties: [], rollout_percentage: 20, variant: null }])
        expect(result.preservedFields).toEqual([])
    })

    it('preserves user-edited key and applies other template values', () => {
        const flagWithKey = { ...baseFlag, key: 'my-custom-key' }
        const templateValues = {
            key: 'template-key',
            filters: { groups: [{ properties: [], rollout_percentage: 50, variant: null }] },
        }

        const result = mergeTemplateValues(flagWithKey, templateValues, new Set(['key']))

        expect(result.updatedFlag.key).toBe('my-custom-key')
        expect(result.updatedFlag.filters?.groups).toEqual([{ properties: [], rollout_percentage: 50, variant: null }])
        expect(result.preservedFields).toEqual(['flag key'])
    })

    it('preserves multiple user-edited fields', () => {
        const editedFlag = { ...baseFlag, key: 'my-key', name: 'My description' }
        const templateValues = {
            key: 'template-key',
            name: 'Template description',
            active: true,
            filters: { groups: [{ properties: [], rollout_percentage: 100, variant: null }] },
        }

        const result = mergeTemplateValues(editedFlag, templateValues, new Set(['key', 'name', 'filters']))

        expect(result.updatedFlag.key).toBe('my-key')
        expect(result.updatedFlag.name).toBe('My description')
        expect(result.updatedFlag.active).toBe(true)
        expect(result.updatedFlag.filters).toEqual(editedFlag.filters)
        expect(result.preservedFields).toEqual(['flag key', 'description', 'release conditions'])
    })

    it('does not overwrite existing key with template key when flag already has a key', () => {
        const flagWithKey = { ...baseFlag, key: 'existing-key' }
        const templateValues = { key: 'template-key' }

        const result = mergeTemplateValues(flagWithKey, templateValues, new Set())

        expect(result.updatedFlag.key).toBe('existing-key')
    })

    it('sets template key when flag key is empty', () => {
        const templateValues = { key: 'template-key' }

        const result = mergeTemplateValues(baseFlag, templateValues, new Set())

        expect(result.updatedFlag.key).toBe('template-key')
    })

    it('merges template filters with existing flag filters', () => {
        const flagWithFilters = {
            ...baseFlag,
            filters: {
                groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                payloads: { true: '{"existing": true}' },
            },
        } as unknown as FeatureFlagType

        const templateValues = {
            filters: { groups: [{ properties: [], rollout_percentage: 20, variant: null }] },
        }

        const result = mergeTemplateValues(flagWithFilters, templateValues, new Set())

        expect(result.updatedFlag.filters?.groups).toEqual([{ properties: [], rollout_percentage: 20, variant: null }])
        expect(result.updatedFlag.filters?.payloads).toEqual({ true: '{"existing": true}' })
    })
})
