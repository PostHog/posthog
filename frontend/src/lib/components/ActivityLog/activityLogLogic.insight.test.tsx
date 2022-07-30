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
import { insightsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'
import React from 'react'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/insights/activity/`]: {
                        results: insightsActivityResponseJson,
                        next: 'a provided url',
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.INSIGHT, describer: insightActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/Insight/all')
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
                JSON.stringify(humanize(insightsActivityResponseJson, insightActivityDescriber))
            )
        })
    })
    describe('when scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/insights/activity/`]: {
                        results: insightsActivityResponseJson,
                        next: 'a provided url',
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: ActivityScope.INSIGHT, id: 7, describer: insightActivityDescriber })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/Insight/7')
        })

        it('loads on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
        })
    })

    describe('when starting at page 4', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [`/api/projects/${MOCK_TEAM_ID}/insights/7/activity/`]: (req) => {
                        const isOnPageFour = req.url.searchParams.get('page') === '4'

                        return [
                            200,
                            {
                                results: isOnPageFour ? insightsActivityResponseJson : [],
                                next: 'a provided url',
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            logic = activityLogLogic({
                scope: ActivityScope.INSIGHT,
                id: 7,
                describer: insightActivityDescriber,
                startingPage: 4,
            })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/Insight/7')
        })

        it('loads data from page 4 on mount', async () => {
            await expectLogic(logic).toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])

            expect(JSON.stringify(logic.values.humanizedActivity)).toEqual(
                JSON.stringify(humanize(insightsActivityResponseJson, insightActivityDescriber))
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
                    'On test insight, peter changed the name to "finish"'
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
                    'changed details'
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
                    'On test insight, peter changed details'
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
                    'On test insight, peter changed the short id to "changed"'
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
                    'On test insight, peter changed the name to "changed"'
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
                    'On test insight, peter changed the description to "changed"'
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

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'On test insight, peter favorited the insight'
                )
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

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    'On test insight, peter un-favorited the insight'
                )
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
                    'On test insight, peter added the tag 3'
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
                    'On test insight, peter removed the tag 3'
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
                    'On test insight, peter added to dashboard added'
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
                    'On test insight, peter removed from dashboard removed'
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
