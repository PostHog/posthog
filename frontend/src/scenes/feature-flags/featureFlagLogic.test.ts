import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    CohortType,
    FeatureFlagGroupType,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
    ScheduledChangeModels,
    ScheduledChangeOperationType,
    ScheduledChangeType,
} from '~/types'
import { FeatureFlagFilters } from '~/types'

import { TemplateKey } from 'products/feature_flags/frontend/featureFlagTemplateConstants'
import type { CopyFlagsDependencyRequirementsResponseApi } from 'products/feature_flags/frontend/generated/api.schemas'

import * as defaultReleaseConditionsModule from './defaultReleaseConditionsLogic'
import {
    DefaultReleaseConditionsResponse,
    defaultReleaseConditionsLogic,
    resolveDefaultReleaseConditions,
} from './defaultReleaseConditionsLogic'
import { detectFeatureFlagChanges } from './featureFlagConfirmationLogic'
import {
    NEW_FLAG,
    convertIndexBasedPayloadsToVariantKeys,
    dependencyActionLabel,
    dependencyDisabledReason,
    featureFlagLogic,
    hasDirectFlagDependency,
    hasMultipleVariantsActive,
    hasStaticCohortDependency,
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
            'keyed by variant index',
            variants,
            { 0: '{"color":"red"}', 1: '{"color":"blue"}' },
            { control: '{"color":"red"}', test: '{"color":"blue"}' },
        ],
        [
            'numeric-string variant keys (regression)',
            [
                { key: '2', rollout_percentage: 50 },
                { key: '0', rollout_percentage: 50 },
            ],
            { 0: '{"for":"variant-2"}', 1: '{"for":"variant-0"}' },
            { '2': '{"for":"variant-2"}', '0': '{"for":"variant-0"}' },
        ],
        [
            'skips indices without a matching variant',
            variants,
            { 0: '{"color":"red"}', 5: '{"orphan":true}' },
            { control: '{"color":"red"}' },
        ],
    ])('converts multivariate payloads %s', (_label, vars, payloads, expected) => {
        expect(convertIndexBasedPayloadsToVariantKeys(vars, payloads)).toEqual(expected)
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

        initKeaTests()
        logic = featureFlagLogic({ id: 1 })
        logic.mount()

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

    describe('applyTemplate', () => {
        const EXPECTED_VARIANTS = partial({
            variants: [partial({ key: 'control' }), partial({ key: 'test' })],
        })

        const TEMPLATE_EXPECTATIONS: Array<{
            id: TemplateKey
            expectedMultivariate: unknown
        }> = [
            { id: 'simple', expectedMultivariate: null },
            { id: 'targeted', expectedMultivariate: null },
            { id: 'multivariate', expectedMultivariate: EXPECTED_VARIANTS },
            { id: 'targeted-multivariate', expectedMultivariate: EXPECTED_VARIANTS },
        ]

        it.each(TEMPLATE_EXPECTATIONS)(
            'clears encrypted-payload state when switching a remote configuration flag to $id',
            async ({ id, expectedMultivariate }) => {
                const MOCK_REMOTE_CONFIG_FLAG: FeatureFlagType = {
                    ...logic.values.featureFlag,
                    is_remote_configuration: true,
                    has_encrypted_payloads: true,
                    filters: {
                        ...logic.values.featureFlag.filters,
                        payloads: { true: 'encrypted-ciphertext' },
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.setFeatureFlag(MOCK_REMOTE_CONFIG_FLAG)
                }).toDispatchActions(['setFeatureFlag'])

                await expectLogic(logic, () => {
                    logic.actions.applyTemplate(id)
                })
                    .toDispatchActions(['applyTemplate', 'setFeatureFlag', 'resetEncryptedPayload'])
                    .toMatchValues({
                        featureFlag: partial({
                            is_remote_configuration: false,
                            has_encrypted_payloads: false,
                            filters: partial({
                                multivariate: expectedMultivariate,
                                payloads: { true: '' },
                            }),
                        }),
                    })

                // The encrypted ciphertext must not survive under any payload key.
                expect(Object.values(logic.values.featureFlag.filters.payloads ?? {})).not.toContain(
                    'encrypted-ciphertext'
                )
            }
        )

        it('prepends org default groups ahead of template groups when default conditions are enabled', async () => {
            const DEFAULT_GROUP = { properties: [], rollout_percentage: 10, variant: null }
            // The shared singleton is warmed to a disabled value on mount, so seed its cache with
            // enabled defaults before applyTemplate reads it.
            defaultReleaseConditionsLogic.actions.loadDefaultReleaseConditionsSuccess({
                enabled: true,
                default_groups: [DEFAULT_GROUP],
            })

            await expectLogic(logic, () => {
                logic.actions.applyTemplate('targeted')
            }).toDispatchActions(['applyTemplate', 'setFeatureFlag'])

            const groups = logic.values.featureFlag.filters.groups
            expect(groups[0]).toMatchObject(DEFAULT_GROUP)
            expect(groups.length).toBeGreaterThan(1)
        })

        it('preserves variant payloads when applying a template to a non-encrypted flag', async () => {
            const MOCK_NON_ENCRYPTED_FLAG: FeatureFlagType = {
                ...logic.values.featureFlag,
                is_remote_configuration: false,
                has_encrypted_payloads: false,
                filters: {
                    ...logic.values.featureFlag.filters,
                    payloads: { control: '{"x":1}', test: '{"y":2}' },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(MOCK_NON_ENCRYPTED_FLAG)
            }).toDispatchActions(['setFeatureFlag'])

            await expectLogic(logic, () => {
                logic.actions.applyTemplate('multivariate')
            })
                .toDispatchActions(['applyTemplate', 'setFeatureFlag'])
                .toMatchValues({
                    featureFlag: partial({
                        is_remote_configuration: false,
                        has_encrypted_payloads: false,
                        filters: partial({
                            payloads: { control: '{"x":1}', test: '{"y":2}' },
                        }),
                    }),
                })
        })

        it('does not access the store after unmounting mid-apply', async () => {
            // applyTemplate awaits release conditions before reading values again. Unmounting during
            // that await (navigating away, or the auto-apply from a ?template= param racing a fast
            // unmount) must not touch a store path that no longer exists — that used to throw
            // "Can not find path ... in the store" and surface as an unhandled rejection.
            let resolveRelease: (value: DefaultReleaseConditionsResponse | null) => void = () => {}
            const pendingRelease = new Promise<DefaultReleaseConditionsResponse | null>((resolve) => {
                resolveRelease = resolve
            })
            const spy = jest
                .spyOn(defaultReleaseConditionsModule, 'resolveDefaultReleaseConditions')
                .mockReturnValue(pendingRelease)

            const rejections: unknown[] = []
            const onRejection = (error: unknown): void => {
                rejections.push(error)
            }
            process.on('unhandledRejection', onRejection)

            try {
                // Listener parks on the pending release conditions, then we navigate away.
                logic.actions.applyTemplate('targeted')
                logic.unmount()

                // Resuming after unmount must bail instead of reading values.featureFlag.
                resolveRelease(null)
                await pendingRelease
                await new Promise((resolve) => setTimeout(resolve, 0))
            } finally {
                process.off('unhandledRejection', onRejection)
                spy.mockRestore()
            }

            expect(rejections).toEqual([])
        })
    })

    describe('setRemoteConfigEnabled', () => {
        it('clears encrypted-payload state when toggling remote config off', async () => {
            const MOCK_REMOTE_CONFIG_FLAG: FeatureFlagType = {
                ...logic.values.featureFlag,
                is_remote_configuration: true,
                has_encrypted_payloads: true,
                filters: {
                    ...logic.values.featureFlag.filters,
                    payloads: { true: 'encrypted-ciphertext' },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(MOCK_REMOTE_CONFIG_FLAG)
            }).toDispatchActions(['setFeatureFlag'])

            await expectLogic(logic, () => {
                logic.actions.setRemoteConfigEnabled(false)
            })
                .toDispatchActions(['setRemoteConfigEnabled', 'resetEncryptedPayload'])
                .toMatchValues({
                    featureFlag: partial({
                        is_remote_configuration: false,
                        has_encrypted_payloads: false,
                        filters: partial({
                            payloads: { true: '' },
                        }),
                    }),
                })

            // The encrypted ciphertext must not survive under any payload key.
            expect(Object.values(logic.values.featureFlag.filters.payloads ?? {})).not.toContain('encrypted-ciphertext')
        })

        it('does not reset encrypted payload state when toggling off a non-encrypted flag', async () => {
            const MOCK_REMOTE_CONFIG_PLAIN_FLAG: FeatureFlagType = {
                ...logic.values.featureFlag,
                is_remote_configuration: true,
                has_encrypted_payloads: false,
                filters: {
                    ...logic.values.featureFlag.filters,
                    payloads: { true: 'plain-payload' },
                },
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(MOCK_REMOTE_CONFIG_PLAIN_FLAG)
            }).toDispatchActions(['setFeatureFlag'])

            await expectLogic(logic, () => {
                logic.actions.setRemoteConfigEnabled(false)
            })
                .toDispatchActions(['setRemoteConfigEnabled'])
                .toNotHaveDispatchedActions(['resetEncryptedPayload'])
                .toMatchValues({
                    featureFlag: partial({
                        is_remote_configuration: false,
                        has_encrypted_payloads: false,
                        filters: partial({
                            payloads: { true: 'plain-payload' },
                        }),
                    }),
                })
        })
    })

    describe('setFeatureFlagFilters', () => {
        it.each([
            ['an empty payload snapshot', {}],
            ['a stale payload snapshot', { true: '{"enabled":false}' }],
        ])('preserves boolean payloads when release conditions update from %s', async (_, incomingPayloads) => {
            const payload = '{"enabled":true}'

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('filters', {
                    ...logic.values.featureFlag.filters,
                    payloads: { true: payload },
                })
            }).toMatchValues({
                featureFlag: partial({
                    filters: partial({
                        payloads: { true: payload },
                    }),
                }),
            })

            const updatedConditionFilters: FeatureFlagFilters = {
                ...logic.values.featureFlag.filters,
                groups: [
                    {
                        properties: [
                            {
                                key: '$browser',
                                value: 'Chrome',
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 42,
                        variant: null,
                    },
                ],
                payloads: incomingPayloads,
            }

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagFilters(updatedConditionFilters, {})
            }).toMatchValues({
                featureFlag: partial({
                    filters: partial({
                        groups: updatedConditionFilters.groups,
                        payloads: { true: payload },
                    }),
                }),
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

        it('does not throw and detects changes when a filter value is a bigint', () => {
            // Property values can be bigint (PropertyFilterBaseValue); raw JSON.stringify throws on them.
            const filtersWithBigIntId = (value: bigint): FeatureFlagFilters => ({
                groups: [
                    {
                        properties: [
                            { key: 'id', value, type: PropertyFilterType.Person, operator: PropertyOperator.Exact },
                        ],
                        rollout_percentage: 100,
                        variant: null,
                    },
                ],
            })
            const originalFlag = { ...MOCK_FEATURE_FLAG, filters: filtersWithBigIntId(BigInt('9007199254740993')) }
            const changedFlag = { ...MOCK_FEATURE_FLAG, filters: filtersWithBigIntId(BigInt('9007199254740994')) }

            let changes: string[] = []
            expect(() => {
                changes = detectFeatureFlagChanges(originalFlag, changedFlag)
            }).not.toThrow()
            expect(changes).toContain('Release conditions changed')
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

    describe('hasUnsavedChanges selector (drives beforeUnload dialog)', () => {
        // The beforeUnload hook reads this selector to decide whether to warn on navigation.
        // User form edits go through kea-forms' setFeatureFlagValue / setFeatureFlagValues,
        // which update only `featureFlag`. `originalFeatureFlag` is the baseline from server load.

        it('is false after the flag loads cleanly', async () => {
            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })

        it('becomes true after the name is edited via the form', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('name', 'Edited name')
            }).toMatchValues({ hasUnsavedChanges: true })
        })

        it('becomes true after the key is edited via the form', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('key', 'edited-key')
            }).toMatchValues({ hasUnsavedChanges: true })
        })

        it('becomes true after filters change via the form', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('filters', {
                    ...logic.values.featureFlag.filters,
                    groups: [{ properties: [], rollout_percentage: 42, variant: null }],
                })
            }).toMatchValues({ hasUnsavedChanges: true })
        })

        it('returns to false when the edited value is reverted to the loaded state', async () => {
            const originalName = logic.values.featureFlag.name
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('name', 'temp-edit')
            }).toMatchValues({ hasUnsavedChanges: true })

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('name', originalName)
            }).toMatchValues({ hasUnsavedChanges: false })
        })

        it('tracks changes when the whole form is replaced via setFeatureFlagValues', async () => {
            await expectLogic(logic, () => {
                // Form `defaults` narrow `ensure_experience_continuity` to `boolean`, but
                // FeatureFlagType allows `boolean | null`. The runtime accepts either —
                // the cast bridges the form-vs-entity type gap that kea-typegen surfaces.
                logic.actions.setFeatureFlagValues({
                    ...logic.values.featureFlag,
                    name: 'Bulk edit',
                } as Parameters<typeof logic.actions.setFeatureFlagValues>[0])
            }).toMatchValues({ hasUnsavedChanges: true })
        })
    })

    describe('urlToAction preserves in-progress edits', () => {
        // Regression for https://github.com/PostHog/posthog/issues/58656 — when the user
        // dismisses the beforeUnload prompt, urlToAction must not silently reload the
        // flag and wipe their in-progress edits. The guard must sit *above* the
        // editFeatureFlag dispatch, because its listener also calls loadFeatureFlag()
        // whenever editing === true.

        it('preserves an in-progress edit on a PUSH navigation when the form is dirty', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('name', 'Edited but not saved')
            }).toMatchValues({ hasUnsavedChanges: true, isFormDirty: true })

            await expectLogic(logic, () => {
                router.actions.push(urls.featureFlag(1))
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['editFeatureFlag'])

            expect(logic.values.featureFlag.name).toBe('Edited but not saved')
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it('preserves an in-progress edit on a PUSH to the same URL with ?edit=true', async () => {
            // Realistic visibilitychange / re-push path: the user is already in edit mode,
            // so the URL carries `?edit=true`. Without the early-return above editFeatureFlag,
            // its listener (`if (editing) loadFeatureFlag()`) would still wipe the form.
            await expectLogic(logic, () => {
                logic.actions.setFeatureFlagValue('name', 'Edited with edit=true in url')
            }).toMatchValues({ hasUnsavedChanges: true, isFormDirty: true })

            await expectLogic(logic, () => {
                router.actions.push(`${urls.featureFlag(1)}?edit=true`)
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['editFeatureFlag'])

            expect(logic.values.featureFlag.name).toBe('Edited with edit=true in url')
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it.each([
            ['sourceId=42', `${urls.featureFlag('new')}?sourceId=42`],
            ['type=multivariate', `${urls.featureFlag('new')}?type=multivariate`],
            ['template=experiment', `${urls.featureFlag('new')}?template=experiment`],
            ['intent=remote-config', `${urls.featureFlag('new')}?intent=remote-config`],
        ])('skips the new-flag template re-load on a dirty PUSH carrying %s', async (_label, targetUrl) => {
            // Pin that the dirty guard also short-circuits the special new-flag
            // re-load branches (sourceId / type / template / intent) inside `urlToAction`.
            // Park the router at a non-matching path first so the `new`-keyed logic's
            // afterMount doesn't see those query params at mount time and prefetch.
            router.actions.push('/')
            const newLogic = featureFlagLogic({ id: 'new' })
            newLogic.mount()
            await expectLogic(newLogic).toFinishAllListeners()

            await expectLogic(newLogic, () => {
                newLogic.actions.setFeatureFlagValue('name', 'Draft new flag')
            }).toMatchValues({ isFormDirty: true })

            await expectLogic(newLogic, () => {
                router.actions.push(targetUrl)
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['editFeatureFlag'])

            expect(newLogic.values.featureFlag.name).toBe('Draft new flag')
            newLogic.unmount()
        })

        it('still reloads the flag on a PUSH navigation when the form is clean', async () => {
            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })

            await expectLogic(logic, () => {
                router.actions.push(urls.featureFlag(1))
            }).toDispatchActions(['loadFeatureFlag'])
        })
    })

    describe('default release conditions on new flags', () => {
        const groupDefault: FeatureFlagGroupType = {
            properties: [
                {
                    key: 'is_dev',
                    type: PropertyFilterType.Group,
                    value: ['true'],
                    operator: PropertyOperator.Exact,
                    group_type_index: 1,
                },
            ],
            rollout_percentage: 100,
            variant: null,
            aggregation_group_type_index: 1,
        }

        async function mountNewFlag(defaultConditions: {
            enabled: boolean
            default_groups: FeatureFlagGroupType[]
        }): Promise<ReturnType<typeof featureFlagLogic.build>> {
            // Seed the shared singleton's cache before the new-flag loader reads it; useMocks lands
            // too late since the logic is warmed to a disabled value on mount in beforeEach.
            defaultReleaseConditionsLogic.actions.loadDefaultReleaseConditionsSuccess(defaultConditions)
            // Park at a non-matching path so the `new`-keyed logic doesn't prefetch off stale params.
            router.actions.push('/')
            const newLogic = featureFlagLogic({ id: 'new' })
            newLogic.mount()
            await expectLogic(newLogic).toFinishAllListeners()
            return newLogic
        }

        it('applies an enabled group-targeted default and mirrors the aggregation onto the new flag', async () => {
            const newLogic = await mountNewFlag({ enabled: true, default_groups: [groupDefault] })

            expect(newLogic.values.featureFlag.filters.groups).toEqual([groupDefault])
            expect(newLogic.values.featureFlag.filters.aggregation_group_type_index).toBe(1)
            newLogic.unmount()
        })

        it('leaves a new flag on user targeting when the default config is disabled', async () => {
            const newLogic = await mountNewFlag({ enabled: false, default_groups: [groupDefault] })

            expect(newLogic.values.featureFlag.filters.groups).toEqual([
                { properties: [], rollout_percentage: 0, variant: null },
            ])
            expect(newLogic.values.featureFlag.filters.aggregation_group_type_index).toBeUndefined()
            newLogic.unmount()
        })
    })

    describe('experiment loading', () => {
        it('loads experiment data when feature flag has an experiment linked', async () => {
            const flagWithExperiment = {
                ...MOCK_FEATURE_FLAG,
                id: 2,
                experiment_set: [MOCK_EXPERIMENT.id],
                experiment_set_metadata: [{ id: MOCK_EXPERIMENT.id, name: MOCK_EXPERIMENT.name, is_running: true }],
            }

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

            const experimentLogic = featureFlagLogic({ id: 2 })
            experimentLogic.mount()

            // The loader awaits the experiment inline before returning the flag,
            // so loadExperimentSuccess lands before loadFeatureFlagSuccess.
            await expectLogic(experimentLogic)
                .toDispatchActions(['loadFeatureFlag', 'loadExperimentSuccess', 'loadFeatureFlagSuccess'])
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

            const noExperimentLogic = featureFlagLogic({ id: 3 })
            noExperimentLogic.mount()

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

            testLogic.mount()

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

            testLogic.mount()

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

            testLogic.mount()

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsSuccess'])
                .toMatchValues({ dependentFlags: [] })

            testLogic.unmount()
        })

        it('handles API failure gracefully and returns empty array', async () => {
            silenceKeaLoadersErrors()
            const flag = { ...MOCK_FEATURE_FLAG, id: 14 }

            const testLogic = featureFlagLogic({ id: 14 })

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

            testLogic.mount()

            await expectLogic(testLogic, () => {
                testLogic.actions.loadFeatureFlag()
            })
                .toDispatchActions(['loadFeatureFlagSuccess', 'loadDependentFlags', 'loadDependentFlagsFailure'])
                .toMatchValues({ dependentFlags: [], dependentFlagsLoading: false })

            testLogic.unmount()
            resumeKeaLoadersErrors()
        })
    })

    describe('copying flags', () => {
        it('sends dependency copy options and resets them after success', async () => {
            const targetProjectId = MOCK_DEFAULT_PROJECT.id + 1
            let capturedCopyBody: Record<string, unknown> | null = null
            let capturedRequirementsBody: Record<string, unknown> | null = null

            useMocks({
                get: {
                    '/api/organizations/:organization_id/feature_flags/:feature_flag_key': () => [200, []],
                },
                post: {
                    '/api/organizations/:organization_id/feature_flags/copy_flags/dependency_requirements': async ({
                        request,
                    }) => {
                        capturedRequirementsBody = (await request.json()) as Record<string, unknown>
                        return [
                            200,
                            {
                                can_copy_dependencies: true,
                                dependency_count: 1,
                                copied_dependency_keys: ['parent-flag'],
                                reused_dependency_keys: [],
                                warnings: [],
                                reason: '1 dependency flag can be copied.',
                            },
                        ]
                    },
                    '/api/organizations/:organization_id/feature_flags/copy_flags': async ({ request }) => {
                        capturedCopyBody = (await request.json()) as Record<string, unknown>
                        return [
                            200,
                            {
                                success: [
                                    {
                                        id: MOCK_FEATURE_FLAG.id,
                                        key: MOCK_FEATURE_FLAG.key,
                                        name: MOCK_FEATURE_FLAG.name,
                                        active: true,
                                        team_id: targetProjectId,
                                        copied_dependency_keys: ['parent-flag'],
                                    },
                                ],
                                failed: [],
                            },
                        ]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag({
                    ...MOCK_FEATURE_FLAG,
                    filters: {
                        ...MOCK_FEATURE_FLAG.filters,
                        groups: [
                            {
                                rollout_percentage: 100,
                                properties: [
                                    {
                                        key: '123',
                                        type: PropertyFilterType.Flag,
                                        value: 'true',
                                        operator: PropertyOperator.FlagEvaluatesTo,
                                    },
                                ],
                            },
                        ],
                    },
                })
                logic.actions.setCopyDestinationProject(targetProjectId)
            }).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])

            expect(capturedRequirementsBody).toMatchObject({
                feature_flag_key: MOCK_FEATURE_FLAG.key,
                from_project: MOCK_DEFAULT_PROJECT.id,
                target_project_ids: [targetProjectId],
            })

            logic.actions.setCopySchedule(true)
            logic.actions.setDisableCopiedFlag(true)
            logic.actions.setCopyDependencies(true)

            await expectLogic(logic, () => {
                logic.actions.copyFlag()
            }).toDispatchActions(['copyFlagSuccess'])

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.copyDependencies).toBe(false)

            expect(capturedCopyBody).toMatchObject({
                feature_flag_key: MOCK_FEATURE_FLAG.key,
                from_project: MOCK_DEFAULT_PROJECT.id,
                target_project_ids: [targetProjectId],
                copy_schedule: true,
                disable_copied_flag: true,
                copy_dependencies: true,
            })
        })

        it('clears dependency requirements when the availability check fails', async () => {
            const targetProjectId = MOCK_DEFAULT_PROJECT.id + 1
            let requirementsCallCount = 0

            useMocks({
                post: {
                    '/api/organizations/:organization_id/feature_flags/copy_flags/dependency_requirements': () => {
                        requirementsCallCount += 1

                        if (requirementsCallCount === 1) {
                            return [
                                200,
                                {
                                    can_copy_dependencies: true,
                                    dependency_count: 1,
                                    copied_dependency_keys: ['parent-flag'],
                                    reused_dependency_keys: [],
                                    warnings: [],
                                    reason: '1 dependency flag can be copied.',
                                },
                            ]
                        }

                        return [500, { error: 'Unable to check dependency availability' }]
                    },
                },
            })

            logic.actions.setFeatureFlag({
                ...MOCK_FEATURE_FLAG,
                filters: {
                    ...MOCK_FEATURE_FLAG.filters,
                    groups: [
                        {
                            rollout_percentage: 100,
                            properties: [
                                {
                                    key: '123',
                                    type: PropertyFilterType.Flag,
                                    value: 'true',
                                    operator: PropertyOperator.FlagEvaluatesTo,
                                },
                            ],
                        },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setCopyDestinationProject(targetProjectId)
            }).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])
            logic.actions.setCopyDependencies(true)

            await expectLogic(logic, () => {
                logic.actions.setCopyDestinationProject(targetProjectId + 1)
            }).toDispatchActions(['loadCopyDependencyRequirementsFailure'])

            expect(logic.values.copyDependencies).toBe(false)
            expect(logic.values.copyDependencyRequirements?.can_copy_dependencies).toBe(false)
            expect(logic.values.copyDependencyRequirements?.reason).toContain('Unable to check dependency availability')
        })

        it('refreshes dependency requirements and clears opt-in when the source flag changes', async () => {
            const targetProjectId = MOCK_DEFAULT_PROJECT.id + 1
            let requirementsCallCount = 0

            const flagWithDependency = (dependencyId: string): FeatureFlagType => ({
                ...MOCK_FEATURE_FLAG,
                filters: {
                    ...MOCK_FEATURE_FLAG.filters,
                    groups: [
                        {
                            rollout_percentage: 100,
                            properties: [
                                {
                                    key: dependencyId,
                                    type: PropertyFilterType.Flag,
                                    value: 'true',
                                    operator: PropertyOperator.FlagEvaluatesTo,
                                },
                            ],
                        },
                    ],
                },
            })

            useMocks({
                get: {
                    '/api/organizations/:organization_id/feature_flags/:feature_flag_key': () => [200, []],
                },
                post: {
                    '/api/organizations/:organization_id/feature_flags/copy_flags/dependency_requirements': () => {
                        requirementsCallCount += 1

                        return [
                            200,
                            {
                                can_copy_dependencies: true,
                                dependency_count: 1,
                                copied_dependency_keys: [`parent-flag-${requirementsCallCount}`],
                                reused_dependency_keys: [],
                                warnings: [],
                                reason: '1 dependency flag can be copied.',
                            },
                        ]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(flagWithDependency('123'))
                logic.actions.setCopyDestinationProject(targetProjectId)
            }).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])

            logic.actions.setCopyDependencies(true)

            await expectLogic(logic, () => {
                logic.actions.setFeatureFlag(flagWithDependency('456'))
            }).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])

            expect(requirementsCallCount).toBe(2)
            expect(logic.values.copyDependencies).toBe(false)
            expect(logic.values.copyDependencyRequirements?.copied_dependency_keys).toEqual(['parent-flag-2'])
        })

        it('ignores stale dependency requirements when the destination changes before the first request resolves', async () => {
            jest.useFakeTimers()
            const firstTargetProjectId = MOCK_DEFAULT_PROJECT.id + 1
            const secondTargetProjectId = MOCK_DEFAULT_PROJECT.id + 2
            type DependencyRequirementsMockResponse = [number, Record<string, unknown>]
            const pendingRequests = new Map<number, (response: DependencyRequirementsMockResponse) => void>()
            const waitForPendingRequest = async (projectId: number): Promise<void> => {
                for (let attempt = 0; attempt < 10; attempt++) {
                    if (pendingRequests.has(projectId)) {
                        return
                    }
                    await Promise.resolve()
                }
                throw new Error(`Missing dependency requirements request for project ${projectId}`)
            }

            useMocks({
                post: {
                    '/api/organizations/:organization_id/feature_flags/copy_flags/dependency_requirements': async ({
                        request,
                    }) => {
                        const body = (await request.json()) as { target_project_ids: number[] }
                        const projectId = body.target_project_ids[0]

                        return await new Promise<DependencyRequirementsMockResponse>((resolve) => {
                            pendingRequests.set(projectId, resolve)
                        })
                    },
                },
            })

            logic.actions.setFeatureFlag({
                ...MOCK_FEATURE_FLAG,
                filters: {
                    ...MOCK_FEATURE_FLAG.filters,
                    groups: [
                        {
                            rollout_percentage: 100,
                            properties: [
                                {
                                    key: '123',
                                    type: PropertyFilterType.Flag,
                                    value: 'true',
                                    operator: PropertyOperator.FlagEvaluatesTo,
                                },
                            ],
                        },
                    ],
                },
            })

            logic.actions.setCopyDestinationProject(firstTargetProjectId)
            await jest.advanceTimersByTimeAsync(300)
            await waitForPendingRequest(firstTargetProjectId)

            logic.actions.setCopyDestinationProject(secondTargetProjectId)
            await jest.advanceTimersByTimeAsync(300)
            await waitForPendingRequest(secondTargetProjectId)

            pendingRequests.get(secondTargetProjectId)?.([
                200,
                {
                    can_copy_dependencies: true,
                    dependency_count: 1,
                    copied_dependency_keys: ['second-parent-flag'],
                    reused_dependency_keys: [],
                    warnings: [],
                    reason: '1 dependency flag can be copied.',
                },
            ])

            await expectLogic(logic).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])
            expect(logic.values.copyDependencyRequirements?.copied_dependency_keys).toEqual(['second-parent-flag'])

            pendingRequests.get(firstTargetProjectId)?.([
                200,
                {
                    can_copy_dependencies: true,
                    dependency_count: 1,
                    copied_dependency_keys: ['first-parent-flag'],
                    reused_dependency_keys: [],
                    warnings: [],
                    reason: '1 dependency flag can be copied.',
                },
            ])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.copyDestinationProject).toBe(secondTargetProjectId)
            expect(logic.values.copyDependencyRequirements?.copied_dependency_keys).toEqual(['second-parent-flag'])
        })

        it('ignores stale dependency requirement failures after the destination changes', async () => {
            jest.useFakeTimers()
            const firstTargetProjectId = MOCK_DEFAULT_PROJECT.id + 1
            const secondTargetProjectId = MOCK_DEFAULT_PROJECT.id + 2
            type DependencyRequirementsMockResponse = [number, Record<string, unknown>]
            const pendingRequests = new Map<number, (response: DependencyRequirementsMockResponse) => void>()
            const waitForPendingRequest = async (projectId: number): Promise<void> => {
                for (let attempt = 0; attempt < 10; attempt++) {
                    if (pendingRequests.has(projectId)) {
                        return
                    }
                    await Promise.resolve()
                }
                throw new Error(`Missing dependency requirements request for project ${projectId}`)
            }

            useMocks({
                post: {
                    '/api/organizations/:organization_id/feature_flags/copy_flags/dependency_requirements': async ({
                        request,
                    }) => {
                        const body = (await request.json()) as { target_project_ids: number[] }
                        const projectId = body.target_project_ids[0]

                        return await new Promise<DependencyRequirementsMockResponse>((resolve) => {
                            pendingRequests.set(projectId, resolve)
                        })
                    },
                },
            })

            logic.actions.setFeatureFlag({
                ...MOCK_FEATURE_FLAG,
                filters: {
                    ...MOCK_FEATURE_FLAG.filters,
                    groups: [
                        {
                            rollout_percentage: 100,
                            properties: [
                                {
                                    key: '123',
                                    type: PropertyFilterType.Flag,
                                    value: 'true',
                                    operator: PropertyOperator.FlagEvaluatesTo,
                                },
                            ],
                        },
                    ],
                },
            })

            logic.actions.setCopyDestinationProject(firstTargetProjectId)
            await jest.advanceTimersByTimeAsync(300)
            await waitForPendingRequest(firstTargetProjectId)

            logic.actions.setCopyDestinationProject(secondTargetProjectId)
            await jest.advanceTimersByTimeAsync(300)
            await waitForPendingRequest(secondTargetProjectId)

            pendingRequests.get(secondTargetProjectId)?.([
                200,
                {
                    can_copy_dependencies: true,
                    dependency_count: 1,
                    copied_dependency_keys: ['second-parent-flag'],
                    reused_dependency_keys: [],
                    warnings: [],
                    reason: '1 dependency flag can be copied.',
                },
            ])

            await expectLogic(logic).toDispatchActions(['loadCopyDependencyRequirementsSuccess'])
            expect(logic.values.copyDependencyRequirements?.copied_dependency_keys).toEqual(['second-parent-flag'])

            pendingRequests.get(firstTargetProjectId)?.([500, { error: 'Unable to check dependency availability' }])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.copyDestinationProject).toBe(secondTargetProjectId)
            expect(logic.values.copyDependencyRequirements?.copied_dependency_keys).toEqual(['second-parent-flag'])
        })
    })

    describe('schedule ordering', () => {
        const makeScheduledChange = (overrides: Partial<ScheduledChangeType>): ScheduledChangeType => ({
            id: 1,
            team_id: MOCK_DEFAULT_PROJECT.id,
            record_id: MOCK_FEATURE_FLAG.id,
            model_name: ScheduledChangeModels.FeatureFlag,
            payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
            scheduled_at: '2026-01-01T00:00:00Z',
            executed_at: null,
            failure_reason: null,
            created_at: '2026-01-01T00:00:00Z',
            created_by: MOCK_DEFAULT_BASIC_USER,
            is_recurring: false,
            recurrence_interval: null,
            cron_expression: null,
            last_executed_at: null,
            end_date: null,
            ...overrides,
        })

        const schedulesUrl = `/api/projects/${MOCK_DEFAULT_PROJECT.id}/scheduled_changes`

        it.each([
            {
                // Mirrors the issue: a recurring change created first must not float above sooner one-time changes.
                desc: 'interleaves recurring and one-time changes by next firing time, soonest first',
                results: [
                    makeScheduledChange({ id: 1, scheduled_at: '2026-05-02T15:00:00Z', is_recurring: true }),
                    makeScheduledChange({ id: 2, scheduled_at: '2026-05-01T14:00:00Z' }),
                    makeScheduledChange({ id: 3, scheduled_at: '2026-07-04T14:58:00Z' }),
                    makeScheduledChange({ id: 4, scheduled_at: '2026-06-13T18:59:00Z' }),
                ],
                expectedIds: [2, 1, 4, 3],
            },
            {
                desc: 'breaks ties by id when scheduled_at is equal',
                results: [
                    makeScheduledChange({ id: 7, scheduled_at: '2026-05-01T00:00:00Z' }),
                    makeScheduledChange({ id: 3, scheduled_at: '2026-05-01T00:00:00Z' }),
                    makeScheduledChange({ id: 5, scheduled_at: '2026-05-01T00:00:00Z' }),
                ],
                expectedIds: [3, 5, 7],
            },
            {
                desc: 'excludes executed changes',
                results: [
                    makeScheduledChange({ id: 1, scheduled_at: '2026-05-01T00:00:00Z' }),
                    makeScheduledChange({
                        id: 2,
                        scheduled_at: '2026-04-01T00:00:00Z',
                        executed_at: '2026-04-01T00:00:00Z',
                    }),
                ],
                expectedIds: [1],
            },
        ])('$desc', async ({ results, expectedIds }) => {
            useMocks({ get: { [schedulesUrl]: () => [200, { results }] } })
            await expectLogic(logic, () => {
                logic.actions.loadScheduledChanges()
            }).toDispatchActions(['loadScheduledChangesSuccess'])

            await expectLogic(logic).toMatchValues({
                activeSchedules: expectedIds.map((id) => partial({ id })),
            })
        })

        it('orders completed changes most-recent first', async () => {
            useMocks({
                get: {
                    [schedulesUrl]: () => [
                        200,
                        {
                            results: [
                                makeScheduledChange({
                                    id: 1,
                                    scheduled_at: '2026-05-01T00:00:00Z',
                                    executed_at: '2026-05-01T00:00:00Z',
                                }),
                                makeScheduledChange({
                                    id: 2,
                                    scheduled_at: '2026-07-01T00:00:00Z',
                                    executed_at: '2026-07-01T00:00:00Z',
                                }),
                                makeScheduledChange({
                                    id: 3,
                                    scheduled_at: '2026-06-01T00:00:00Z',
                                    executed_at: '2026-06-01T00:00:00Z',
                                }),
                            ],
                        },
                    ],
                },
            })
            await expectLogic(logic, () => {
                logic.actions.loadScheduledChanges()
            }).toDispatchActions(['loadScheduledChangesSuccess'])

            await expectLogic(logic).toMatchValues({
                completedSchedules: [partial({ id: 2 }), partial({ id: 3 }), partial({ id: 1 })],
            })
        })

        it('orders completed changes by execution time, not scheduled time', async () => {
            useMocks({
                get: {
                    [schedulesUrl]: () => [
                        200,
                        {
                            results: [
                                // Scheduled first but, after a delay, executed last.
                                makeScheduledChange({
                                    id: 1,
                                    scheduled_at: '2026-05-01T00:00:00Z',
                                    executed_at: '2026-05-03T00:00:00Z',
                                }),
                                makeScheduledChange({
                                    id: 2,
                                    scheduled_at: '2026-05-02T00:00:00Z',
                                    executed_at: '2026-05-02T00:00:00Z',
                                }),
                            ],
                        },
                    ],
                },
            })
            await expectLogic(logic, () => {
                logic.actions.loadScheduledChanges()
            }).toDispatchActions(['loadScheduledChangesSuccess'])

            await expectLogic(logic).toMatchValues({
                completedSchedules: [partial({ id: 1 }), partial({ id: 2 })],
            })
        })
    })

    describe('default release conditions', () => {
        const conditionsUrl = `/api/environments/${MOCK_DEFAULT_PROJECT.id}/default_release_conditions/`

        it('applies org default groups to a new flag when default conditions are enabled', async () => {
            const DEFAULT_GROUP = { properties: [], rollout_percentage: 30, variant: null }
            // Seed the shared singleton's cache with enabled defaults before the new-flag loader reads it
            // (it's warmed to a disabled value on mount).
            defaultReleaseConditionsLogic.actions.loadDefaultReleaseConditionsSuccess({
                enabled: true,
                default_groups: [DEFAULT_GROUP],
            })

            const newLogic = featureFlagLogic({ id: 'new' })
            newLogic.mount()
            await expectLogic(newLogic).toDispatchActions(['loadFeatureFlagSuccess'])

            const groups = newLogic.values.featureFlag.filters.groups
            expect(groups[0]).toMatchObject(DEFAULT_GROUP)
            expect(groups.length).toBe(1)

            newLogic.unmount()
        })

        describe('resolveDefaultReleaseConditions', () => {
            it('returns the cached value without fetching when one is already loaded', async () => {
                const cached = {
                    enabled: true,
                    default_groups: [{ properties: [], rollout_percentage: 25, variant: null }],
                }
                // toBe asserts the same object reference, so a fetched copy would fail the assertion.
                await expect(resolveDefaultReleaseConditions(cached, MOCK_DEFAULT_PROJECT.id)).resolves.toBe(cached)
            })

            it('fetches directly when the cache is empty', async () => {
                const fetched = {
                    enabled: true,
                    default_groups: [{ properties: [], rollout_percentage: 10, variant: null }],
                }
                useMocks({ get: { [conditionsUrl]: () => [200, fetched] } })
                await expect(resolveDefaultReleaseConditions(null, MOCK_DEFAULT_PROJECT.id)).resolves.toEqual(fetched)
            })

            it('returns null without fetching when no team is available', async () => {
                await expect(resolveDefaultReleaseConditions(null, undefined)).resolves.toBeNull()
            })

            it('returns null when the fetch fails so new flag creation is not blocked', async () => {
                // The graceful-failure path warns to the console by design.
                const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
                useMocks({ get: { [conditionsUrl]: () => [500, {}] } })
                await expect(resolveDefaultReleaseConditions(null, MOCK_DEFAULT_PROJECT.id)).resolves.toBeNull()
                warnSpy.mockRestore()
            })
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

describe('hasDirectFlagDependency', () => {
    it.each([
        {
            filters: { groups: { properties: [] } },
            expected: false,
            desc: 'groups is not an array',
        },
        {
            filters: { groups: [null] },
            expected: false,
            desc: 'group is null',
        },
        {
            filters: { groups: [{ properties: { type: PropertyFilterType.Flag } }] },
            expected: false,
            desc: 'properties is not an array',
        },
        {
            filters: { groups: [{ properties: [null] }] },
            expected: false,
            desc: 'property is null',
        },
        {
            filters: createFilters({
                groups: [
                    {
                        properties: [
                            {
                                key: '123',
                                type: PropertyFilterType.Flag,
                                value: 'true',
                                operator: PropertyOperator.FlagEvaluatesTo,
                            },
                        ],
                    },
                ],
            }),
            expected: true,
            desc: 'group has a flag property',
        },
    ])('returns $expected when $desc', ({ filters, expected }) => {
        expect(hasDirectFlagDependency({ ...MOCK_FEATURE_FLAG, filters: filters as FeatureFlagFilters })).toBe(expected)
    })
})

describe('dependency copy labels', () => {
    const dependencyRequirements = (
        overrides: Partial<CopyFlagsDependencyRequirementsResponseApi> = {}
    ): CopyFlagsDependencyRequirementsResponseApi => ({
        can_copy_dependencies: true,
        dependency_count: 1,
        copied_dependency_keys: ['parent-flag'],
        reused_dependency_keys: [],
        warnings: [],
        reason: '1 dependency flag can be copied.',
        ...overrides,
    })

    const actionLabelCases: {
        desc: string
        loading: boolean
        req: CopyFlagsDependencyRequirementsResponseApi | null
        expected: string
    }[] = [
        {
            desc: 'requirements are loading',
            loading: true,
            req: dependencyRequirements({ can_copy_dependencies: false, reason: 'Dependency copying is disabled.' }),
            expected: 'Copy dependencies: Checking',
        },
        {
            desc: 'requirements are missing',
            loading: false,
            req: null,
            expected: 'Copy dependencies: Checking',
        },
        {
            desc: 'dependencies can be copied',
            loading: false,
            req: dependencyRequirements({ copied_dependency_keys: ['parent-flag', 'grandparent-flag'] }),
            expected: 'Copy dependencies: 2 missing',
        },
        {
            desc: 'dependency copying has warnings',
            loading: false,
            req: dependencyRequirements({
                can_copy_dependencies: false,
                copied_dependency_keys: [],
                warnings: ['Dependency copying is unavailable.'],
                reason: 'Dependency copying is unavailable.',
            }),
            expected: 'Copy dependencies: Unavailable',
        },
        {
            desc: 'all dependencies already exist',
            loading: false,
            req: dependencyRequirements({
                can_copy_dependencies: false,
                copied_dependency_keys: [],
                reused_dependency_keys: ['parent-flag'],
                warnings: [],
                reason: 'All dependencies already exist in the destination project.',
            }),
            expected: 'Copy dependencies: Already satisfied',
        },
    ]

    const disabledReasonCases: {
        desc: string
        loading: boolean
        req: CopyFlagsDependencyRequirementsResponseApi | null
        expected: string | undefined
    }[] = [
        {
            desc: 'requirements are loading',
            loading: true,
            req: dependencyRequirements({ can_copy_dependencies: false, reason: 'Dependency copying is disabled.' }),
            expected: 'Checking dependency availability',
        },
        {
            desc: 'requirements are missing',
            loading: false,
            req: null,
            expected: 'Checking dependency availability',
        },
        {
            desc: 'dependencies can be copied',
            loading: false,
            req: dependencyRequirements(),
            expected: undefined,
        },
        {
            desc: 'dependency copying is unavailable',
            loading: false,
            req: dependencyRequirements({
                can_copy_dependencies: false,
                reason: 'Dependency copying is unavailable.',
            }),
            expected: 'Dependency copying is unavailable.',
        },
    ]

    it.each(actionLabelCases)('returns "$expected" as the action label when $desc', ({ loading, req, expected }) => {
        expect(dependencyActionLabel(loading, req)).toBe(expected)
    })

    it.each(disabledReasonCases)(
        'returns "$expected" as the disabled reason when $desc',
        ({ loading, req, expected }) => {
            expect(dependencyDisabledReason(loading, req)).toBe(expected)
        }
    )
})

describe('hasStaticCohortDependency', () => {
    const cohorts = [
        { id: 12, is_static: true },
        { id: 13, is_static: false },
    ] as CohortType[]

    it.each([
        {
            filters: { groups: { properties: [] } },
            expected: false,
            desc: 'groups is not an array',
        },
        {
            filters: { groups: [null] },
            expected: false,
            desc: 'group is null',
        },
        {
            filters: { groups: [{ properties: { type: PropertyFilterType.Cohort, value: 12 } }] },
            expected: false,
            desc: 'properties is not an array',
        },
        {
            filters: { groups: [{ properties: [null] }] },
            expected: false,
            desc: 'property is null',
        },
        {
            filters: createFilters({
                groups: [
                    {
                        properties: [
                            {
                                key: 'id',
                                type: PropertyFilterType.Cohort,
                                value: 13,
                                operator: PropertyOperator.In,
                            },
                        ],
                    },
                ],
            }),
            expected: false,
            desc: 'cohort is behavioral',
        },
        {
            filters: createFilters({
                groups: [
                    {
                        properties: [
                            {
                                key: 'id',
                                type: PropertyFilterType.Cohort,
                                value: 12,
                                operator: PropertyOperator.In,
                            },
                        ],
                    },
                ],
            }),
            expected: true,
            desc: 'cohort is static',
        },
    ])('returns $expected when $desc', ({ filters, expected }) => {
        expect(
            hasStaticCohortDependency({ ...MOCK_FEATURE_FLAG, filters: filters as FeatureFlagFilters }, cohorts)
        ).toBe(expected)
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
