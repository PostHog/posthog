import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { ActivityChange, ActivityLogItem, ActivityScope, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { featureFlagsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { render, RenderResult } from '@testing-library/react'
import '@testing-library/jest-dom'
import { teamLogic } from 'scenes/teamLogic'
import { Provider } from 'kea'
import React from 'react'

const keaRender = (children: React.ReactFragment): RenderResult => render(<Provider>{children}</Provider>)

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/activity/': {
                        results: featureFlagsActivityResponseJson,
                        next: 'a provided url',
                    },
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
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })

        it('increments the page when loading the next page', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchNextPageSuccess({ results: [], total_count: 0 }) // page 1
                logic.actions.fetchNextPageSuccess({ results: [], total_count: 0 }) // page 2
            }).toMatchValues({ page: 2 })
        })

        it('decrements the page when loading the previous page', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchNextPageSuccess({ results: [], total_count: 0 }) // page 1
                logic.actions.fetchNextPageSuccess({ results: [], total_count: 0 }) // page 2
                logic.actions.fetchPreviousPageSuccess({ results: [], total_count: 0 }) // page 1
            }).toMatchValues({ page: 1 })
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                nextPageLoading: false,
                previousPageLoading: false,
                nextPageURL: 'a provided url',
            })

            // react fragments confuse equality check so,
            // stringify to confirm this value has the humanized version of the response
            // detailed tests for humanization are below
            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })
    describe('when scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': {
                        results: featureFlagsActivityResponseJson,
                        next: 'a provided url',
                    },
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
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })
    })

    describe('when starting at page 4', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': (req) => {
                        const isOnPageFour = req.url.searchParams.get('page') === '4'

                        return [
                            200,
                            {
                                results: isOnPageFour ? featureFlagsActivityResponseJson : [],
                                next: 'a provided url',
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({
                scope: ActivityScope.FEATURE_FLAG,
                id: 7,
                describer: flagActivityDescriber,
                startingPage: 4,
            })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/7')
        })

        it('loads data from page 4 on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(featureFlagsActivityResponseJson, flagActivityDescriber))
            )
        })
    })

    describe('humanizing feature flags', () => {
        const makeAPIItem = (
            name: string,
            activity: string,
            changes: ActivityChange[] | null = null
        ): ActivityLogItem => ({
            user: { first_name: 'peter', email: 'peter@posthog.com' },
            activity,
            scope: ActivityScope.FEATURE_FLAG,
            item_id: '7',
            detail: {
                changes: changes,
                name,
            },
            created_at: '2022-02-05T16:28:39.594Z',
        })

        async function testSetup(activityLogItem: ActivityLogItem): Promise<void> {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': {
                        results: [activityLogItem],
                    },
                },
            })
            initKeaTests()
            teamLogic.mount()
            logic = activityLogLogic({ scope: ActivityScope.FEATURE_FLAG, id: 7, describer: flagActivityDescriber })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
        }

        it('can handle rollout percentage change', async () => {
            await testSetup(
                makeAPIItem('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'rollout_percentage',
                        after: '36',
                    },
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed rollout percentage to 36% on test flag'
            )
        })

        it('can humanize more than one change', async () => {
            await testSetup(
                makeAPIItem('test flag', 'updated', [
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
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed rollout percentage to 36% on test flag'
            )
            expect(keaRender(<>{actual[1].description}</>).container).toHaveTextContent(
                'changed the description to "strawberry" on test flag'
            )
        })

        it('can handle filter change - boolean value, no conditions', async () => {
            await testSetup(
                makeAPIItem('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        after: { groups: [{ properties: [], rollout_percentage: 99 }], multivariate: null },
                    },
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'set the flag test flag to apply to 99% of all users'
            )
        })

        it('can handle filter change with cohort', async () => {
            await testSetup(
                makeAPIItem('with cohort', 'updated', [
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
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'set the flag with cohort to apply to 100% ofID 98, and 100% ofID 411'
            )
        })

        it('can describe a simple rollout percentage change', async () => {
            await testSetup(
                makeAPIItem('with simple rollout change', 'updated', [
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
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'set the flag with simple rollout change to apply to 77% of all users'
            )
        })

        it('describes a null rollout percentage as 100%', async () => {
            await testSetup(
                makeAPIItem('with null rollout change', 'updated', [
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
                ])
            )
            const actual = logic.values.activity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'set the flag with null rollout change to apply to 100% ofemail = someone@somewhere.dev'
            )
        })

        it('can describe two property changes', async () => {
            await testSetup(
                makeAPIItem('with two changes', 'updated', [
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
                ])
            )
            const actual = logic.values.humanizedActivity

            expect(keaRender(<>{actual[0].description}</>).container).toHaveTextContent(
                'set the flag with two changes to apply to 76% ofInitial Browser = Chrome , and 99% ofInitial Browser Version = 100'
            )
        })
    })
})
