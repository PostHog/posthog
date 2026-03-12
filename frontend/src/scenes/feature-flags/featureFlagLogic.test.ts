import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'
import { FeatureFlagFilters } from '~/types'

import { detectFeatureFlagChanges } from './featureFlagConfirmationLogic'
import {
    NEW_FLAG,
    featureFlagLogic,
    hasMultipleVariantsActive,
    hasZeroRollout,
    slugifyFeatureFlagKey,
    validateFeatureFlagKey,
} from './featureFlagLogic'

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
})

const createFilters = (overrides: Partial<FeatureFlagFilters> = {}): FeatureFlagFilters => ({
    groups: [],
    ...overrides,
})

describe('hasZeroRollout', () => {
    it.each([
        { filters: undefined, expected: false, desc: 'undefined filters' },
        { filters: null, expected: false, desc: 'null filters' },
        { filters: createFilters(), expected: false, desc: 'empty groups' },
        {
            filters: createFilters({ groups: [{ rollout_percentage: 0 }] }),
            expected: true,
            desc: 'single group at 0%',
        },
        {
            filters: createFilters({ groups: [{ rollout_percentage: 0 }, { rollout_percentage: 0 }] }),
            expected: true,
            desc: 'all groups at 0%',
        },
        {
            filters: createFilters({ groups: [{ rollout_percentage: 0 }, { rollout_percentage: 50 }] }),
            expected: false,
            desc: 'mixed groups',
        },
        {
            filters: createFilters({ groups: [{ rollout_percentage: 100 }] }),
            expected: false,
            desc: 'single group at 100%',
        },
        {
            filters: createFilters({ groups: [{ rollout_percentage: null }] }),
            expected: false,
            desc: 'null rollout_percentage (defaults to 100%)',
        },
        {
            filters: createFilters({ groups: [{ rollout_percentage: undefined }] }),
            expected: false,
            desc: 'undefined rollout_percentage (defaults to 100%)',
        },
    ])('returns $expected when $desc', ({ filters, expected }) => {
        expect(hasZeroRollout(filters)).toBe(expected)
    })
})

describe('hasMultipleVariantsActive', () => {
    it.each([
        { filters: undefined, expected: false, desc: 'undefined filters' },
        { filters: null, expected: false, desc: 'null filters' },
        { filters: createFilters(), expected: false, desc: 'no multivariate config' },
        {
            filters: createFilters({ multivariate: { variants: [] } }),
            expected: false,
            desc: 'empty variants',
        },
        {
            filters: createFilters({ multivariate: { variants: [{ key: 'control', rollout_percentage: 50 }] } }),
            expected: false,
            desc: 'single active variant',
        },
        {
            filters: createFilters({
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            }),
            expected: true,
            desc: 'two active variants',
        },
        {
            filters: createFilters({
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 100 },
                        { key: 'test', rollout_percentage: 0 },
                    ],
                },
            }),
            expected: false,
            desc: 'two variants, but one shipped',
        },
        {
            filters: createFilters({
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 0 },
                        { key: 'test', rollout_percentage: 0 },
                    ],
                },
            }),
            expected: false,
            desc: 'all variants at 0%',
        },
        {
            filters: createFilters({
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 0 },
                        { key: 'test-2', rollout_percentage: 50 },
                    ],
                },
            }),
            expected: true,
            desc: 'two of three variants active',
        },
    ])('returns $expected when $desc', ({ filters, expected }) => {
        expect(hasMultipleVariantsActive(filters)).toBe(expected)
    })
})

describe('slugifyFeatureFlagKey', () => {
    it.each([
        { input: 'my-flag', expected: 'my-flag', desc: 'valid kebab-case key passes through' },
        { input: 'camelCase', expected: 'camelCase', desc: 'preserves case by default' },
        { input: 'under_score', expected: 'under_score', desc: 'underscores pass through' },
        { input: 'UPPER', expected: 'UPPER', desc: 'uppercase preserved' },
        { input: 'foo bar', expected: 'foo-bar', desc: 'spaces become hyphens' },
        { input: 'foo  bar', expected: 'foo-bar', desc: 'multiple spaces collapse to single hyphen' },
        { input: 'foo.bar', expected: 'foobar', desc: 'dots are stripped' },
        { input: 'foo,bar', expected: 'foobar', desc: 'commas are stripped' },
        { input: 'foo?bar=baz', expected: 'foobarbaz', desc: 'query string chars are stripped' },
        { input: 'foo/bar', expected: 'foobar', desc: 'slashes are stripped' },
        { input: 'héllo', expected: 'hello', desc: 'accented characters are normalized' },
        { input: '  leading', expected: 'leading', desc: 'leading whitespace is trimmed' },
        { input: 'trailing ', expected: 'trailing-', desc: 'trailing whitespace kept (for typing)' },
        { input: 'a--b', expected: 'a-b', desc: 'consecutive hyphens collapsed' },
    ])('returns "$expected" when $desc', ({ input, expected }) => {
        expect(slugifyFeatureFlagKey(input)).toBe(expected)
    })

    it.each([
        { input: 'My Flag Name', expected: 'my-flag-name', desc: 'lowercases and converts spaces' },
        { input: '  padded  ', expected: 'padded', desc: 'trims both ends' },
        { input: 'UPPER CASE', expected: 'upper-case', desc: 'lowercases uppercase' },
    ])('with fromTitleInput=true returns "$expected" when $desc', ({ input, expected }) => {
        expect(slugifyFeatureFlagKey(input, { fromTitleInput: true })).toBe(expected)
    })
})

describe('validateFeatureFlagKey', () => {
    it.each([
        { key: 'my-flag', desc: 'kebab-case' },
        { key: 'camelCase', desc: 'camelCase' },
        { key: 'under_score', desc: 'underscores' },
        { key: '123', desc: 'numeric' },
        { key: 'MIX-ed_123', desc: 'mixed valid chars' },
        { key: 'a', desc: 'single character' },
    ])('accepts valid key: $desc', ({ key }) => {
        expect(validateFeatureFlagKey(key)).toBeUndefined()
    })

    it.each([
        { key: 'foo bar', error: 'Only letters', desc: 'spaces' },
        { key: 'foo.bar', error: 'Only letters', desc: 'dots' },
        { key: 'foo,bar', error: 'Only letters', desc: 'commas' },
        { key: 'foo?bar', error: 'Only letters', desc: 'question marks' },
        { key: 'foo/bar', error: 'Only letters', desc: 'slashes' },
        { key: 'foo\\bar', error: 'Only letters', desc: 'backslashes' },
    ])('rejects key with $desc', ({ key, error }) => {
        expect(validateFeatureFlagKey(key)).toContain(error)
    })

    it('rejects empty key', () => {
        expect(validateFeatureFlagKey('')).toBe('Please set a key')
    })

    it('rejects key exceeding 400 characters', () => {
        expect(validateFeatureFlagKey('a'.repeat(401))).toContain('400 characters')
    })

    it('accepts key at exactly 400 characters', () => {
        expect(validateFeatureFlagKey('a'.repeat(400))).toBeUndefined()
    })
})
