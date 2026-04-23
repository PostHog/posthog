import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'
import { FeatureFlagFilters } from '~/types'

import { detectFeatureFlagChanges } from './featureFlagConfirmationLogic'
import {
    NEW_FLAG,
    convertIndexBasedPayloadsToVariantKeys,
    featureFlagLogic,
    hasMultipleVariantsActive,
    hasZeroRollout,
    indexToVariantKeyFeatureFlagPayloads,
    scheduleDateFromStoredISO,
    scheduleDateToProjectTzISO,
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

describe('payload conversion helpers', () => {
    const variants = [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]

    it.each([
        [
            'already keyed by variant key',
            {
                control: '{"color":"red"}',
                test: '{"color":"blue"}',
            },
            {
                control: '{"color":"red"}',
                test: '{"color":"blue"}',
            },
        ],
        [
            'keyed by variant index',
            {
                0: '{"color":"red"}',
                1: '{"color":"blue"}',
            },
            {
                control: '{"color":"red"}',
                test: '{"color":"blue"}',
            },
        ],
        [
            'with mixed keys while preferring explicit variant keys',
            {
                control: '{"color":"red"}',
                0: '{"color":"green"}',
                1: '{"color":"blue"}',
            },
            {
                control: '{"color":"red"}',
                test: '{"color":"blue"}',
            },
        ],
    ])('converts multivariate payloads %s', (_label, payloads, expected) => {
        expect(convertIndexBasedPayloadsToVariantKeys(variants, payloads)).toEqual(expected)
    })

    it('keeps boolean flag payload handling unchanged', () => {
        expect(
            indexToVariantKeyFeatureFlagPayloads({
                filters: {
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                    multivariate: null,
                    payloads: {
                        true: '{"enabled":true}',
                        false: '{"enabled":false}',
                    },
                },
            } as unknown as FeatureFlagType)
        ).toEqual({
            filters: {
                groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                multivariate: null,
                payloads: {
                    true: '{"enabled":true}',
                },
            },
        })
    })
})

describe('schedule timezone helpers', () => {
    // Scenarios covered: project tz east and west of browser tz, and matching the browser.
    it.each([
        ['America/New_York', '2026-02-05T10:00:00', '2026-02-05T15:00:00.000Z'],
        ['America/Los_Angeles', '2026-02-05T10:00:00', '2026-02-05T18:00:00.000Z'],
        ['UTC', '2026-02-05T10:00:00', '2026-02-05T10:00:00.000Z'],
        ['Asia/Tokyo', '2026-02-05T10:00:00', '2026-02-05T01:00:00.000Z'],
    ])('scheduleDateToProjectTzISO interprets the wall clock in %s', (timezone, wallClock, expectedIso) => {
        // Build a browser-local Dayjs regardless of the Jest host timezone.
        const local = dayjs(wallClock)
        expect(scheduleDateToProjectTzISO(local, timezone)).toBe(expectedIso)
    })

    it.each([
        ['America/New_York', '2026-02-05T15:00:00.000Z', '2026-02-05 10:00'],
        ['America/Los_Angeles', '2026-02-05T18:00:00.000Z', '2026-02-05 10:00'],
        ['UTC', '2026-02-05T10:00:00.000Z', '2026-02-05 10:00'],
        ['Asia/Tokyo', '2026-02-05T01:00:00.000Z', '2026-02-05 10:00'],
    ])(
        'scheduleDateFromStoredISO exposes the project-timezone wall clock as a local Dayjs in %s',
        (timezone, stored, expectedWallClock) => {
            const restored = scheduleDateFromStoredISO(stored, timezone)
            expect(restored.format('YYYY-MM-DD HH:mm')).toBe(expectedWallClock)
        }
    )

    it.each([['America/New_York'], ['America/Los_Angeles'], ['UTC'], ['Asia/Tokyo']])(
        'round-trips the user-entered wall clock in %s',
        (timezone) => {
            const userPicked = dayjs('2026-02-05T10:30:00')
            const iso = scheduleDateToProjectTzISO(userPicked, timezone)
            const restored = scheduleDateFromStoredISO(iso, timezone)
            expect(restored.format('YYYY-MM-DD HH:mm')).toBe('2026-02-05 10:30')
        }
    )

    // end_date is persisted as end-of-day (HH:mm:ss.999) — verify sub-second precision survives the trip.
    it.each([['America/New_York'], ['America/Los_Angeles'], ['UTC'], ['Asia/Tokyo']])(
        'preserves millisecond precision through the round trip in %s',
        (timezone) => {
            const endOfDay = dayjs('2026-02-05T00:00:00').tz(timezone, true).endOf('day')
            const iso = endOfDay.toISOString()
            const restored = scheduleDateFromStoredISO(iso, timezone)
            expect(restored.format('YYYY-MM-DD HH:mm:ss.SSS')).toBe('2026-02-05 23:59:59.999')
        }
    )
})

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
                experiment_set_metadata: [{ id: MOCK_EXPERIMENT.id, name: MOCK_EXPERIMENT.name }],
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
                experiment_set_metadata: null,
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

describe('variant reordering', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagLogic({ id: 1 })
        logic.mount()

        // Set up a multivariate flag with test variants
        logic.actions.setFeatureFlag({
            ...MOCK_FEATURE_FLAG,
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', name: 'Control', rollout_percentage: 33 },
                        { key: 'test-a', name: 'Test A', rollout_percentage: 33 },
                        { key: 'test-b', name: 'Test B', rollout_percentage: 34 },
                    ],
                },
                payloads: { 0: { option: 'default' }, 1: { option: 'variant-a' }, 2: { option: 'variant-b' } },
            },
        })
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('moveVariantUp', () => {
        it('moves variant up by one position', () => {
            logic.actions.moveVariantUp(1) // Move 'test-a' up

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-a')
            expect(variants[1].key).toBe('control')
            expect(variants[2].key).toBe('test-b')
        })

        it('reorders payloads when moving variant up', () => {
            logic.actions.moveVariantUp(1) // Move 'test-a' up

            const payloads = logic.values.featureFlag.filters?.payloads
            expect(payloads?.[0]).toEqual({ option: 'variant-a' }) // test-a payload now at index 0
            expect(payloads?.[1]).toEqual({ option: 'default' }) // control payload now at index 1
            expect(payloads?.[2]).toEqual({ option: 'variant-b' }) // test-b payload stays at index 2
        })

        it('does nothing when trying to move first variant up', () => {
            const originalVariants = [...logic.values.variants]
            logic.actions.moveVariantUp(0)

            expect(logic.values.variants).toEqual(originalVariants)
        })

        it('handles negative indices gracefully', () => {
            const originalVariants = [...logic.values.variants]
            logic.actions.moveVariantUp(-1)

            expect(logic.values.variants).toEqual(originalVariants)
        })
    })

    describe('moveVariantDown', () => {
        it('moves variant down by one position', () => {
            logic.actions.moveVariantDown(0) // Move 'control' down

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-a')
            expect(variants[1].key).toBe('control')
            expect(variants[2].key).toBe('test-b')
        })

        it('reorders payloads when moving variant down', () => {
            logic.actions.moveVariantDown(0) // Move 'control' down

            const payloads = logic.values.featureFlag.filters?.payloads
            expect(payloads?.[0]).toEqual({ option: 'variant-a' }) // test-a payload now at index 0
            expect(payloads?.[1]).toEqual({ option: 'default' }) // control payload now at index 1
            expect(payloads?.[2]).toEqual({ option: 'variant-b' }) // test-b payload stays at index 2
        })

        it('does nothing when trying to move last variant down', () => {
            const originalVariants = [...logic.values.variants]
            logic.actions.moveVariantDown(2) // Try to move last variant down

            expect(logic.values.variants).toEqual(originalVariants)
        })

        it('handles out of bounds indices gracefully', () => {
            const originalVariants = [...logic.values.variants]
            logic.actions.moveVariantDown(10) // Out of bounds index

            expect(logic.values.variants).toEqual(originalVariants)
        })
    })

    describe('reorderVariants', () => {
        it('moves variant from beginning to end', () => {
            logic.actions.reorderVariants(0, 2) // Move 'control' from index 0 to 2

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-a')
            expect(variants[1].key).toBe('test-b')
            expect(variants[2].key).toBe('control')
        })

        it('moves variant from end to beginning', () => {
            logic.actions.reorderVariants(2, 0) // Move 'test-b' from index 2 to 0

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-b')
            expect(variants[1].key).toBe('control')
            expect(variants[2].key).toBe('test-a')
        })

        it('moves variant forward by one position', () => {
            logic.actions.reorderVariants(0, 1) // Move 'control' from index 0 to 1

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-a')
            expect(variants[1].key).toBe('control')
            expect(variants[2].key).toBe('test-b')
        })

        it('moves variant backward by one position', () => {
            logic.actions.reorderVariants(1, 0) // Move 'test-a' from index 1 to 0

            const variants = logic.values.variants
            expect(variants[0].key).toBe('test-a')
            expect(variants[1].key).toBe('control')
            expect(variants[2].key).toBe('test-b')
        })

        it('correctly reorders payloads with complex reordering', () => {
            logic.actions.reorderVariants(0, 2) // Move 'control' from index 0 to 2

            const payloads = logic.values.featureFlag.filters?.payloads
            expect(payloads?.[0]).toEqual({ option: 'variant-a' }) // test-a payload
            expect(payloads?.[1]).toEqual({ option: 'variant-b' }) // test-b payload
            expect(payloads?.[2]).toEqual({ option: 'default' }) // control payload
        })

        it('does nothing when fromIndex equals toIndex', () => {
            const originalVariants = [...logic.values.variants]
            const originalPayloads = { ...logic.values.featureFlag.filters?.payloads }

            logic.actions.reorderVariants(1, 1)

            expect(logic.values.variants).toEqual(originalVariants)
            expect(logic.values.featureFlag.filters?.payloads).toEqual(originalPayloads)
        })

        it('handles invalid indices gracefully', () => {
            const originalVariants = [...logic.values.variants]

            logic.actions.reorderVariants(-1, 1) // Invalid fromIndex
            expect(logic.values.variants).toEqual(originalVariants)

            logic.actions.reorderVariants(1, -1) // Invalid toIndex
            expect(logic.values.variants).toEqual(originalVariants)

            logic.actions.reorderVariants(10, 1) // Out of bounds fromIndex
            expect(logic.values.variants).toEqual(originalVariants)

            logic.actions.reorderVariants(1, 10) // Out of bounds toIndex
            expect(logic.values.variants).toEqual(originalVariants)
        })

        it('preserves all variant properties during reordering', () => {
            logic.actions.reorderVariants(0, 2)

            const variants = logic.values.variants
            expect(variants[0]).toEqual({
                key: 'test-a',
                name: 'Test A',
                rollout_percentage: 33,
            })
            expect(variants[1]).toEqual({
                key: 'test-b',
                name: 'Test B',
                rollout_percentage: 34,
            })
            expect(variants[2]).toEqual({
                key: 'control',
                name: 'Control',
                rollout_percentage: 33,
            })
        })
    })

    describe('payload synchronization edge cases', () => {
        it('handles missing payloads gracefully', () => {
            logic.actions.setFeatureFlag({
                ...logic.values.featureFlag,
                filters: {
                    ...logic.values.featureFlag.filters,
                    payloads: undefined,
                },
            })

            expect(() => logic.actions.reorderVariants(0, 2)).not.toThrow()
            expect(logic.values.variants[0].key).toBe('test-a')
        })

        it('handles sparse payloads correctly', () => {
            logic.actions.setFeatureFlag({
                ...logic.values.featureFlag,
                filters: {
                    ...logic.values.featureFlag.filters,
                    payloads: { 0: { option: 'default' }, 2: { option: 'variant-b' } }, // Missing index 1
                },
            })

            logic.actions.reorderVariants(0, 2)

            const payloads = logic.values.featureFlag.filters?.payloads
            expect(payloads?.[0]).toBeUndefined() // test-a had no payload
            expect(payloads?.[1]).toEqual({ option: 'variant-b' }) // test-b payload
            expect(payloads?.[2]).toEqual({ option: 'default' }) // control payload
        })
    })
})
