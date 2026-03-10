import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { featureFlagIntentWarningLogic } from './featureFlagIntentWarningLogic'
import { featureFlagLogic, NEW_FLAG } from './featureFlagLogic'

describe('featureFlagIntentWarningLogic', () => {
    let flagLogic: ReturnType<typeof featureFlagLogic.build>
    let warningLogic: ReturnType<typeof featureFlagIntentWarningLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': () => [200, { results: [], count: 0 }],
                '/api/projects/:team_id/cohorts/': () => [200, { results: [], count: 0 }],
            },
        })

        flagLogic = featureFlagLogic({ id: 'new' })
        flagLogic.mount()
        warningLogic = featureFlagIntentWarningLogic({ id: 'new' })
        warningLogic.mount()
    })

    afterEach(() => {
        warningLogic.unmount()
        flagLogic.unmount()
    })

    function enableIntentsFeatureFlag(): void {
        enabledFeaturesLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS]: true,
        })
    }

    describe('unreachable conditions (always-on)', () => {
        it.each([
            {
                name: 'broad group before specific group marks second group unreachable',
                groups: [
                    { properties: [], rollout_percentage: 100, variant: null },
                    {
                        properties: [
                            {
                                key: 'email',
                                type: PropertyFilterType.Person,
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                ],
                expectedUnreachable: [1],
            },
            {
                name: 'broad group at end does not trigger unreachable',
                groups: [
                    {
                        properties: [
                            {
                                key: 'email',
                                type: PropertyFilterType.Person,
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                    { properties: [], rollout_percentage: 100, variant: null },
                ],
                expectedUnreachable: [],
            },
            {
                name: 'null rollout_percentage treated as 100%',
                groups: [
                    { properties: [], rollout_percentage: null as number | null, variant: null },
                    {
                        properties: [
                            {
                                key: 'email',
                                type: PropertyFilterType.Person,
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                ],
                expectedUnreachable: [1],
            },
            {
                name: 'multiple unreachable groups detected',
                groups: [
                    { properties: [], rollout_percentage: 100, variant: null },
                    {
                        properties: [
                            {
                                key: 'email',
                                type: PropertyFilterType.Person,
                                value: 'a',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                    {
                        properties: [
                            {
                                key: 'name',
                                type: PropertyFilterType.Person,
                                value: 'b',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 50,
                        variant: null,
                    },
                ],
                expectedUnreachable: [1, 2],
            },
            {
                name: 'group with properties is not broad even at 100%',
                groups: [
                    {
                        properties: [
                            {
                                key: 'email',
                                type: PropertyFilterType.Person,
                                value: 'test@posthog.com',
                                operator: PropertyOperator.Exact,
                            },
                        ],
                        rollout_percentage: 100,
                        variant: null,
                    },
                    { properties: [], rollout_percentage: 50, variant: null },
                ],
                expectedUnreachable: [],
            },
            {
                name: 'single group never unreachable',
                groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                expectedUnreachable: [],
            },
        ])('$name', async ({ groups, expectedUnreachable }) => {
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: { ...NEW_FLAG.filters, groups: groups as FeatureFlagGroupType[] },
            })

            await expectLogic(warningLogic).toMatchValues({
                unreachableGroups: new Set(expectedUnreachable),
            })
        })
    })

    describe('local eval intent', () => {
        it.each([
            {
                name: 'is_not_set operator',
                properties: [{ key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet }],
                expectedIssueContains: '"is not set"',
            },
        ])('detects $name', async ({ properties, expectedIssueContains }) => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [{ properties: properties as AnyPropertyFilter[], rollout_percentage: 100, variant: null }],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues.length).toBeGreaterThanOrEqual(1)
            expect(issues.some((s) => s.toLowerCase().includes(expectedIssueContains.toLowerCase()))).toBe(true)
        })

        it('detects static cohort', async () => {
            enableIntentsFeatureFlag()

            cohortsModel.mount()
            cohortsModel.actions.cohortCreated({
                id: 1,
                name: 'Static Cohort',
                is_static: true,
                filters: { properties: { type: 'AND', values: [] } },
            } as any)

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'id', type: PropertyFilterType.Cohort, value: 1, operator: PropertyOperator.In },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues.some((s) => s.toLowerCase().includes('static cohort'))).toBe(true)
        })

        it('detects behavioral cohort', async () => {
            enableIntentsFeatureFlag()

            cohortsModel.mount()
            cohortsModel.actions.cohortCreated({
                id: 2,
                name: 'Behavioral Cohort',
                is_static: false,
                filters: {
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'AND',
                                values: [{ type: BehavioralFilterKey.Behavioral, key: 'performed_event' }],
                            },
                        ],
                    },
                },
            } as any)

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'id', type: PropertyFilterType.Cohort, value: 2, operator: PropertyOperator.In },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues.some((s) => s.toLowerCase().includes('behavioral'))).toBe(true)
        })

        it('multiple issues across groups are deduplicated', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                        {
                            properties: [
                                { key: 'name', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues.filter((s) => s.includes('"is not set"'))).toHaveLength(1)
        })

        it('experience continuity adds an issue', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                ensure_experience_continuity: true,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [{ properties: [] as AnyPropertyFilter[], rollout_percentage: 100, variant: null }],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues.some((s) => s.toLowerCase().includes('persist'))).toBe(true)
        })

        it('no issues without intent set', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            expect(warningLogic.values.intentIssues).toEqual([])
        })
    })

    describe('prevent flicker intent', () => {
        it.each([
            {
                name: 'non-instant property triggers flicker issue',
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: 'test' },
                ],
                expectedIssueCount: 1,
            },
            {
                name: 'cohort filter triggers flicker issue',
                properties: [{ type: PropertyFilterType.Cohort, value: 1, key: 'id' }],
                expectedIssueCount: 1,
            },
            {
                name: 'cohort and non-instant property produce separate issues',
                properties: [
                    { type: PropertyFilterType.Cohort, value: 1, key: 'id' },
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: 'test' },
                ],
                expectedIssueCount: 2,
            },
            {
                name: 'instant property does not trigger issue',
                properties: [
                    {
                        key: '$geoip_country_code',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: 'US',
                    },
                ],
                expectedIssueCount: 0,
            },
        ])('$name', async ({ properties, expectedIssueCount }) => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('first-page-load')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [{ properties: properties as AnyPropertyFilter[], rollout_percentage: 100, variant: null }],
                },
            })

            expect(warningLogic.values.intentIssues).toHaveLength(expectedIssueCount)
        })

        it('single non-instant property names the property in the message', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('first-page-load')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                    value: 'test',
                                },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues).toHaveLength(1)
            expect(issues[0]).toContain('"email"')
        })

        it('multiple non-instant properties shows count instead of names', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('first-page-load')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                    value: 'test',
                                },
                                {
                                    key: 'name',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                    value: 'test',
                                },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            const issues = warningLogic.values.intentIssues
            expect(issues).toHaveLength(1)
            expect(issues[0]).toContain('2 properties')
        })

        it('no issues without intent set', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    operator: PropertyOperator.Exact,
                                    value: 'test',
                                },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            expect(warningLogic.values.intentIssues).toEqual([])
        })
    })

    describe('co-occurrence', () => {
        it('unreachable groups and intent issues are produced simultaneously', async () => {
            enableIntentsFeatureFlag()

            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        { properties: [], rollout_percentage: 100, variant: null },
                        {
                            properties: [
                                { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 50,
                            variant: null,
                        },
                    ],
                },
            })

            expect(warningLogic.values.unreachableGroups.has(1)).toBe(true)
            expect(warningLogic.values.intentIssues.length).toBeGreaterThanOrEqual(1)
            expect(warningLogic.values.intentIssues.some((s) => s.includes('"is not set"'))).toBe(true)
        })
    })

    describe('feature flag gate', () => {
        it('unreachable conditions shown regardless of intents feature flag', async () => {
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        { properties: [], rollout_percentage: 100, variant: null },
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: 'test',
                                    operator: PropertyOperator.Exact,
                                },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 50,
                            variant: null,
                        },
                    ],
                },
            })

            expect(warningLogic.values.unreachableGroups.has(1)).toBe(true)
        })

        it('invalid intent string produces no issues', async () => {
            enableIntentsFeatureFlag()

            // Simulate setting an invalid intent directly — parseUrlIntent would return undefined,
            // so flagIntent stays null and no issues are produced
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            // flagIntent is null (no valid intent set), so no issues despite problematic properties
            expect(warningLogic.values.flagIntent).toBeNull()
            expect(warningLogic.values.intentIssues).toEqual([])
        })

        it('intent issues suppressed when intents feature flag is off', async () => {
            enabledFeaturesLogic.actions.setFeatureFlags([], {})
            flagLogic.actions.setFlagIntent('local-eval')
            flagLogic.actions.setFeatureFlag({
                ...NEW_FLAG,
                filters: {
                    ...NEW_FLAG.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
                            ] as AnyPropertyFilter[],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            })

            expect(warningLogic.values.intentIssues).toEqual([])
        })
    })
})
