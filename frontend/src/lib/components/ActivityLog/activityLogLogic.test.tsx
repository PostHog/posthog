import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import React from 'react'
import { useMocks } from '~/mocks/jest'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    Describer,
    humanize,
    PersonMerge,
} from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import {
    featureFlagsActivityResponseJson,
    personActivityResponseJson,
} from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { render, RenderResult } from '@testing-library/react'
import '@testing-library/jest-dom'
import { teamLogic } from 'scenes/teamLogic'
import { Provider } from 'kea'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'

const keaRender = (children: React.ReactFragment): RenderResult => render(<Provider>{children}</Provider>)

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/activity/': { results: featureFlagsActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG, describer: flagActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/all')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions([logic.actionCreators.fetchActivity()])
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                activityLoading: false,
            })

            // react fragments confuse equality check so,
            // stringify to confirm this value has the humanized version of the response
            // detailed tests for humanization are below
            expect(JSON.stringify(logic.values.activity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })

    describe('when scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': { results: featureFlagsActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG, id: 7, describer: flagActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/7')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions([logic.actionCreators.fetchActivity()])
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                activityLoading: false,
            })

            // react fragments confuse equality check so,
            // stringify to confirm this value has the humanized version of the response
            // detailed tests for humanization are below
            expect(JSON.stringify(logic.values.activity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })

    describe('when scoped to person', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/person/7/activity': { results: personActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.PERSON, id: 7, describer: personActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/Person/7')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchActivity', 'fetchActivitySuccess'])
        })

        it.todo('can load a page of activity')
    })

    describe('humanzing', () => {
        interface APIMockSetup {
            name: string
            activity: string
            changes?: ActivityChange[] | null
            scope: ActivityScope
            merge?: PersonMerge | null
        }

        const makeAPIItem = ({
            name,
            activity,
            changes = null,
            scope,
            merge = null,
        }: APIMockSetup): ActivityLogItem => ({
            user: { first_name: 'peter', email: 'peter@posthog.com' },
            activity,
            scope,
            item_id: '7',
            detail: {
                changes,
                merge,
                name,
            },
            created_at: '2022-02-05T16:28:39.594Z',
        })

        async function testSetup(
            activityLogItem: ActivityLogItem,
            scope: ActivityScope,
            describer: Describer,
            url: string
        ): Promise<void> {
            useMocks({
                get: {
                    [url]: {
                        results: [activityLogItem],
                    },
                },
            })
            initKeaTests()
            teamLogic.mount()
            logic = activityLogLogic({ scope, id: 7, describer })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
        }

        describe('humanizing persons', () => {
            it('can handle addition of a property', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.PERSON,
                        name: 'test person',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'Person',
                                action: 'changed',
                                field: 'properties',
                                before: {},
                                after: { a: 'b' },
                            },
                        ],
                    }),
                    ActivityScope.PERSON,
                    personActivityDescriber,
                    '/api/person/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'added property a with value: b'
                )
            })

            it('can handle merging people', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.PERSON,
                        name: 'test person',
                        activity: 'people_merged_into',
                        changes: null,
                        merge: {
                            type: 'Person',
                            source: [
                                { distinct_ids: ['a'], properties: {} },
                                { distinct_ids: ['c'], properties: {} },
                            ],
                            target: { distinct_ids: ['d'], properties: {} },
                        },
                    }),
                    ActivityScope.PERSON,
                    personActivityDescriber,
                    '/api/person/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'merged into this person: User A, and User C'
                )
            })

            it('can handle splitting people', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.PERSON,
                        name: 'test person',
                        activity: 'split_person',
                        changes: [
                            {
                                type: 'Person',
                                action: 'changed',
                                field: undefined,
                                before: {},
                                after: { distinct_ids: ['a', 'b'] },
                            },
                        ],
                    }),
                    ActivityScope.PERSON,
                    personActivityDescriber,
                    '/api/person/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'split this person into a, and b'
                )
            })
        })

        describe('humanizing feature flags', () => {
            it('can handle rollout percentage change', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'test flag',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'rollout_percentage',
                                after: '36',
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed rollout percentage to 36% on test flag'
                )
            })

            it('can humanize more than one change', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'test flag',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'rollout_percentage',
                                after: '36',
                            },
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'name',
                                after: 'strawberry',
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed rollout percentage to 36% on test flag'
                )
                expect(keaRender(<>{actual[1].description}</>).container).toHaveTextContent(
                    'changed the description to "strawberry" on test flag'
                )
            })

            it('can handle filter change - boolean value, no conditions', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'test flag',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'filters',
                                after: { groups: [{ properties: [], rollout_percentage: 99 }], multivariate: null },
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'set the flag test flag to apply to 99% of all users'
                )
            })

            it('can handle filter change with cohort', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'with cohort',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'filters',
                                after: {
                                    groups: [
                                        {
                                            properties: [
                                                {
                                                    key: 'id',
                                                    type: 'cohort',
                                                    value: 98,
                                                    operator: null,
                                                },
                                            ],
                                            rollout_percentage: null,
                                        },
                                        {
                                            properties: [
                                                {
                                                    key: 'id',
                                                    type: 'cohort',
                                                    value: 411,
                                                    operator: null,
                                                },
                                            ],
                                            rollout_percentage: 100,
                                        },
                                    ],
                                    multivariate: null,
                                },
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'set the flag with cohort to apply to 100% ofID 98, and 100% ofID 411'
                )
            })

            it('can describe a simple rollout percentage change', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'with simple rollout change',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'filters',
                                before: {
                                    groups: [
                                        {
                                            properties: [],
                                            rollout_percentage: 75,
                                        },
                                    ],
                                    multivariate: null,
                                },
                                after: {
                                    groups: [
                                        {
                                            properties: [],
                                            rollout_percentage: 77,
                                        },
                                    ],
                                    multivariate: null,
                                },
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'set the flag with simple rollout change to apply to 77% of all users'
                )
            })

            it('describes a null rollout percentage as 100%', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'with null rollout change',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'filters',
                                before: {
                                    groups: [
                                        {
                                            properties: [
                                                {
                                                    key: 'id',
                                                    type: 'cohort',
                                                    value: 98,
                                                    operator: null,
                                                },
                                            ],
                                            rollout_percentage: null,
                                        },
                                    ],
                                    multivariate: null,
                                },
                                after: {
                                    groups: [
                                        {
                                            properties: [
                                                {
                                                    key: 'id',
                                                    type: 'cohort',
                                                    value: 98,
                                                    operator: null,
                                                },
                                            ],
                                            rollout_percentage: null,
                                        },
                                        {
                                            properties: [
                                                {
                                                    key: 'email',
                                                    type: 'person',
                                                    value: 'someone@somewhere.dev',
                                                    operator: 'exact',
                                                },
                                            ],
                                            rollout_percentage: null,
                                        },
                                    ],
                                    multivariate: null,
                                },
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'set the flag with null rollout change to apply to 100% ofemail = someone@somewhere.dev'
                )
            })

            it('can describe two property changes', async () => {
                await testSetup(
                    makeAPIItem({
                        scope: ActivityScope.FEATURE_FLAG,
                        name: 'with two changes',
                        activity: 'updated',
                        changes: [
                            {
                                type: 'FeatureFlag',
                                action: 'changed',
                                field: 'filters',
                                before: {
                                    groups: [
                                        {
                                            properties: [
                                                {
                                                    key: '$initial_browser',
                                                    type: 'person',
                                                    value: ['Chrome'],
                                                    operator: 'exact',
                                                },
                                            ],
                                            rollout_percentage: 77,
                                        },
                                        {
                                            properties: [
                                                {
                                                    key: '$initial_browser_version',
                                                    type: 'person',
                                                    value: ['100'],
                                                    operator: 'exact',
                                                },
                                            ],
                                            rollout_percentage: null,
                                        },
                                    ],
                                    multivariate: null,
                                },
                                after: {
                                    groups: [
                                        {
                                            properties: [
                                                {
                                                    key: '$initial_browser',
                                                    type: 'person',
                                                    value: ['Chrome'],
                                                    operator: 'exact',
                                                },
                                            ],
                                            rollout_percentage: 76,
                                        },
                                        {
                                            properties: [
                                                {
                                                    key: '$initial_browser_version',
                                                    type: 'person',
                                                    value: ['100'],
                                                    operator: 'exact',
                                                },
                                            ],
                                            rollout_percentage: 99,
                                        },
                                    ],
                                    multivariate: null,
                                },
                            },
                        ],
                    }),
                    ActivityScope.FEATURE_FLAG,
                    flagActivityDescriber,
                    '/api/projects/@current/feature_flags/7/activity/'
                )
                const actual = logic.values.activity

                expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                    'set the flag with two changes to apply to 76% ofInitial Browser = Chrome , and 99% ofInitial Browser Version = 100'
                )
            })
        })
    })
})
