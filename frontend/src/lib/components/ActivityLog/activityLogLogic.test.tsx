import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
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
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/activity/`]: {
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

        it('can load a page of activity', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                nextPageLoading: false,
                previousPageLoading: false,
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
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`]: {
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
                    [`/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`]: (req) => {
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
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })

        it('can load a page of activity', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(personActivityResponseJson, personActivityDescriber))
            )
        })
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
            logic = activityLogLogic({ scope, id: 7, describer })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()
        }

        const makeTestSetup = (scope: ActivityScope, describer: Describer, url: string) => {
            return async (name: string, activity: string, changes: ActivityChange[] | null, merge?: PersonMerge) => {
                await testSetup(makeAPIItem({ scope, name, activity, changes, merge }), scope, describer, url)
            }
        }

        describe('humanizing persons', () => {
            const personTestSetup = makeTestSetup(
                ActivityScope.PERSON,
                personActivityDescriber,
                '/api/person/7/activity/'
            )
            it('can handle addition of a property', async () => {
                await personTestSetup('test person', 'updated', [
                    {
                        type: 'Person',
                        action: 'changed',
                        field: 'properties',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    "edited this person's properties"
                )
            })

            it('can handle merging people', async () => {
                await personTestSetup('test person', 'people_merged_into', null, {
                    type: 'Person',
                    source: [
                        { distinct_ids: ['a'], properties: {} },
                        { distinct_ids: ['c'], properties: {} },
                    ],
                    target: { distinct_ids: ['d'], properties: {} },
                })
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'merged into this person: User A, and User C'
                )
            })

            it('can handle splitting people', async () => {
                await personTestSetup('test_person', 'split_person', [
                    {
                        type: 'Person',
                        action: 'changed',
                        field: undefined,
                        before: {},
                        after: { distinct_ids: ['a', 'b'] },
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'split this person into a, and b'
                )
            })
        })

        describe('humanizing feature flags', () => {
            const featureFlagsTestSetup = makeTestSetup(
                ActivityScope.FEATURE_FLAG,
                flagActivityDescriber,
                `/api/projects/${MOCK_TEAM_ID}/feature_flags/7/activity/`
            )

            it('can handle soft deletion change', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'deleted',
                        after: 'true',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('deleted test flag')
            })

            it('can handle soft enabling flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'active',
                        after: 'true',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('enabled test flag')
            })

            it('can handle soft disabling flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'active',
                        after: 'false',
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('disabled test flag')
            })

            it('can handle deleting several groups from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
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
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                                {
                                    properties: [],
                                    rollout_percentage: 40,
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
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'removed 2 release conditions on test flag'
                )
            })

            it('can handle deleting a group from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
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
                                {
                                    properties: [],
                                    rollout_percentage: 30,
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
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'removed 1 release condition on test flag'
                )
            })

            it('can handle rollout percentage change', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'rollout_percentage',
                        after: '36',
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed rollout percentage to 36% on test flag'
                )
            })

            it('can handle deleting the first of several groups from a flag', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
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
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                            ],
                            multivariate: null,
                        },
                        after: {
                            groups: [
                                {
                                    properties: [],
                                    rollout_percentage: 30,
                                },
                            ],
                            multivariate: null,
                        },
                    },
                ])

                const actual = logic.values.humanizedActivity
                expect(render(<>{actual[0]?.description}</>).container).toHaveTextContent(
                    'removed 1 release condition on test flag'
                )
            })

            it('can humanize more than one change', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
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

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed rollout percentage to 36%, and changed the description to "strawberry" on test flag'
                )
            })

            it('can handle filter change - boolean value, no conditions', async () => {
                await featureFlagsTestSetup('test flag', 'updated', [
                    {
                        type: 'FeatureFlag',
                        action: 'changed',
                        field: 'filters',
                        after: { groups: [{ properties: [], rollout_percentage: 99 }], multivariate: null },
                    },
                ])

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the filter conditions to apply to 99% of all users on test flag'
                )
            })

            it('can handle filter change with cohort', async () => {
                await featureFlagsTestSetup('with cohort', 'updated', [
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
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the filter conditions to apply to 100% ofID 98, and 100% ofID 411 on with cohort'
                )
            })

            it('can describe a simple rollout percentage change', async () => {
                await featureFlagsTestSetup('with simple rollout change', 'updated', [
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
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the filter conditions to apply to 77% of all users on with simple rollout change'
                )
            })

            it('describes a null rollout percentage as 100%', async () => {
                await featureFlagsTestSetup('with null rollout change', 'updated', [
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
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the filter conditions to apply to 100% ofemail = someone@somewhere.dev on with null rollout change'
                )
            })

            it('can describe two property changes', async () => {
                await featureFlagsTestSetup('with two changes', 'updated', [
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

                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the filter conditions to apply to 76% ofInitial Browser = Chrome , and 99% ofInitial Browser Version = 100 on with two changes'
                )
            })
        })

        describe('humanizing insights', () => {
            const insightTestSetup = makeTestSetup(
                ActivityScope.INSIGHT,
                insightActivityDescriber,
                `/api/projects/${MOCK_TEAM_ID}/insights/activity/`
            )

            it('can handle change of name', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'name',
                        before: 'start',
                        after: 'finish',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the name to "finish" on test insight'
                )
            })

            it('can handle change of filters', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'filters',
                        after: {
                            events: [
                                {
                                    id: '$pageview',
                                    type: 'events',
                                    order: 0,
                                    custom_name: 'First page view',
                                },
                                {
                                    id: '$pageview',
                                    type: 'events',
                                    order: 1,
                                    custom_name: 'Second page view',
                                },
                                {
                                    id: '$pageview',
                                    type: 'events',
                                    order: 2,
                                    custom_name: 'Third page view',
                                },
                            ],
                            layout: 'horizontal',
                            display: 'FunnelViz',
                            insight: 'FUNNELS',
                            interval: 'day',
                            breakdowns: [
                                {
                                    type: 'event',
                                    property: '$browser',
                                },
                            ],
                            exclusions: [],
                            breakdown_type: 'event',
                            funnel_viz_type: 'steps',
                            funnel_window_interval: 16,
                            funnel_window_interval_unit: 'day',
                        },
                    },
                ])
                const actual = logic.values.humanizedActivity

                const renderedDescription = render(<>{actual[0].description}</>).container
                expect(renderedDescription).toHaveTextContent(
                    // text is huge don't assert on entire content
                    'changed details to:Query summary'
                )
            })

            it('can handle change of filters on a retention graph', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'filters',
                        after: {
                            period: 'Week',
                            display: 'ActionsTable',
                            insight: 'RETENTION',
                            properties: [],
                            target_entity: {
                                id: '$pageview',
                                type: 'events',
                            },
                            retention_type: 'retention_first_time',
                            total_intervals: 11,
                            returning_entity: {
                                id: '$pageview',
                                type: 'events',
                            },
                        },
                    },
                ])
                const actual = logic.values.humanizedActivity

                const renderedDescription = render(<>{actual[0].description}</>).container
                expect(renderedDescription).toHaveTextContent(
                    // text is huge don't assert on entire content
                    'changed details on test insight'
                )
            })

            it('can handle soft delete', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'deleted',
                        after: 'true',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('deleted')
            })

            it('can handle change of short id', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'short_id',
                        after: 'changed',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the short id to "changed" on test insight'
                )
            })

            it('can handle change of derived name', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'derived_name',
                        after: 'changed',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the name to "changed" on test insight'
                )
            })

            it('can handle change of description', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'description',
                        after: 'changed',
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'changed the description to "changed" on test insight'
                )
            })

            it('can handle change of favorited', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'favorited',
                        after: true,
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('favorited test insight')
            })

            it('can handle removal of favorited', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'favorited',
                        after: false,
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent('un-favorited test insight')
            })

            it('can handle addition of tags', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'tags',
                        before: ['1', '2'],
                        after: ['1', '2', '3'],
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'added the tag 3 on test insight'
                )
            })

            it('can handle removal of tags', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'tags',
                        before: ['1', '2', '3'],
                        after: ['1', '2'],
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'removed the tag 3 on test insight'
                )
            })

            it('can handle addition of dashboards link', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'dashboards',
                        before: [
                            { id: '1', name: 'anything' },
                            { id: '2', name: 'another' },
                        ],
                        after: [
                            { id: '1', name: 'anything' },
                            { id: '2', name: 'another' },
                            { id: '3', name: 'added' },
                        ],
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'added to dashboard added test insight'
                )
            })

            it('can handle removal of dashboards link', async () => {
                await insightTestSetup('test insight', 'updated', [
                    {
                        type: 'Insight',
                        action: 'changed',
                        field: 'dashboards',
                        before: [
                            { id: '1', name: 'anything' },
                            { id: '2', name: 'another' },
                            { id: '3', name: 'removed' },
                        ],
                        after: [
                            { id: '1', name: 'anything' },
                            { id: '2', name: 'another' },
                        ],
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'removed from dashboard removed test insight'
                )
            })
            const formats = ['png', 'pdf', 'csv']
            formats.map((format) => {
                it(`can handle export of insight to ${format}`, async () => {
                    await insightTestSetup('test insight', 'exported', [
                        {
                            type: 'Insight',
                            action: 'exported',
                            field: 'export_format',
                            before: undefined,
                            after: `something/${format}`,
                        },
                    ])
                    const actual = logic.values.humanizedActivity

                    expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                        `exported the insight test insight as a ${format}`
                    )
                })
            })
        })
    })
})
