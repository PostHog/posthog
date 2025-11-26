import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'
import { render } from '@testing-library/react'

import { makeTestSetup } from 'lib/components/ActivityLog/activityLogLogic.test.setup'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

jest.mock('lib/colors')

describe('the activity log logic', () => {
    describe('humanizing insights', () => {
        const insightTestSetup = makeTestSetup(
            ActivityScope.INSIGHT,
            `/api/environments/${MOCK_TEAM_ID}/insights/activity/`
        )

        it('can handle change of name', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'name',
                    before: 'start',
                    after: 'finish',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter renamed "start" to "finish"'
            )
        })

        it('can handle change of filters', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
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
            expect(renderedDescription).toHaveTextContent('peter changed query definition on test insight')
        })

        it('can handle change of insight query', async () => {
            const insightMock = {
                type: ActivityScope.INSIGHT,
                action: 'changed',
                field: 'query',
                after: {
                    kind: 'TrendsQuery',
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'OR',
                                values: [
                                    {
                                        type: 'event',
                                        key: '$current_url',
                                        operator: 'exact',
                                        value: ['https://hedgebox.net/files/'],
                                    },
                                    {
                                        type: 'event',
                                        key: '$geoip_country_code',
                                        operator: 'exact',
                                        value: ['US', 'AU'],
                                    },
                                ],
                            },
                        ],
                    },
                    filterTestAccounts: false,
                    interval: 'day',
                    dateRange: {
                        date_from: '-7d',
                    },
                    series: [
                        {
                            kind: 'EventsNode',
                            name: '$pageview',
                            custom_name: 'Views',
                            event: '$pageview',
                            properties: [
                                {
                                    type: 'event',
                                    key: '$browser',
                                    operator: 'exact',
                                    value: 'Chrome',
                                },
                                {
                                    type: 'cohort',
                                    key: 'id',
                                    operator: 'in',
                                    value: 2,
                                },
                            ],
                            limit: 100,
                        },
                    ],
                    trendsFilter: {
                        display: 'ActionsAreaGraph',
                    },
                    breakdownFilter: {
                        breakdown: '$geoip_country_code',
                        breakdown_type: 'event',
                    },
                },
            }

            let logic = await insightTestSetup('test insight', 'updated', [insightMock as any])
            let actual = logic.values.humanizedActivity

            let renderedDescription = render(<>{actual[0].description}</>).container
            expect(renderedDescription).toHaveTextContent('peter changed query definition on test insight')

            let renderedExtendedDescription = render(<>{actual[0].extendedDescription}</>).container
            expect(renderedExtendedDescription).toHaveTextContent(
                "QueryACounting \"Views\"Pageviewby total countwhere event'sBrowser= equals Chromeand person belongs to cohortUser in ID 2FiltersEvent'sCurrent URL= equals https://hedgebox.net/files/or event'sCountry code= equals US or AUBreakdown byCountry code"
            )
            ;(insightMock.after.breakdownFilter as BreakdownFilter) = {
                breakdowns: [
                    {
                        property: '$geoip_country_code',
                        type: 'event',
                    },
                    {
                        property: '$session_duration',
                        type: 'session',
                    },
                ],
            }

            logic = await insightTestSetup('test insight', 'updated', [insightMock as any])
            actual = logic.values.humanizedActivity

            renderedDescription = render(<>{actual[0].description}</>).container
            expect(renderedDescription).toHaveTextContent('peter changed query definition on test insight')

            renderedExtendedDescription = render(<>{actual[0].extendedDescription}</>).container
            expect(renderedExtendedDescription).toHaveTextContent(
                "QueryACounting \"Views\"Pageviewby total countwhere event'sBrowser= equals Chromeand person belongs to cohortUser in ID 2FiltersEvent'sCurrent URL= equals https://hedgebox.net/files/or event'sCountry code= equals US or AUBreakdown byCountry code"
            )
        })

        it('can handle change of filters on a retention graph', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
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
            expect(renderedDescription).toHaveTextContent('peter changed query definition on test insight')
        })

        it('can handle soft delete', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'deleted',
                    after: 'true',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter deleted test insight')
        })

        it('can handle change of short id', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'short_id',
                    after: 'changed',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the short id to "changed" on test insight'
            )
        })

        it('can handle change of derived name', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'derived_name',
                    before: 'original',
                    after: 'changed',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter renamed "original" to "changed"'
            )
        })

        it('can handle change of description', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'description',
                    after: 'changed',
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter changed the description to "changed" on test insight'
            )
        })

        it('can handle change of favorited', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'favorited',
                    after: true,
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter favorited test insight')
        })

        it('can handle removal of favorited', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'favorited',
                    after: false,
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('peter un-favorited test insight')
        })

        it('can handle addition of tags', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'tags',
                    before: ['1', '2'],
                    after: ['1', '2', '3'],
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter added tag 3 on test insight'
            )
        })

        it('can handle removal of tags', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'tags',
                    before: ['1', '2', '3'],
                    after: ['1', '2'],
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter removed tag 3 on test insight'
            )
        })

        it('can handle addition and removal of tags', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'tags',
                    before: ['1', '2', '3'],
                    after: ['1', '4', '5'],
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter added tags 45, and removed tags 23 on test insight'
            )
        })

        it('can handle addition of dashboards link', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'dashboards',
                    before: [
                        { id: '1', name: 'anything' },
                        { id: '2', name: 'another' },
                    ],
                    after: [
                        { id: '1', name: 'anything' },
                        { id: '2', name: 'another' },
                        { id: '3', name: 'the-new-one' },
                    ],
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter added test insight to the-new-one'
            )
        })

        it('can handle addition of tile style dashboards link', async () => {
            const logic = await insightTestSetup('test insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'dashboards',
                    before: [
                        { insight: { id: 1 }, dashboard: { id: '1', name: 'anything' } },
                        { insight: { id: 1 }, dashboard: { id: '2', name: 'another' } },
                    ],
                    after: [
                        { insight: { id: 1 }, dashboard: { id: '1', name: 'anything' } },
                        { insight: { id: 1 }, dashboard: { id: '2', name: 'another' } },
                        { insight: { id: 1 }, dashboard: { id: '3', name: 'the-new-one' } },
                    ],
                },
            ])
            const actual = logic.values.humanizedActivity

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'peter added test insight to the-new-one'
            )
        })

        it('can handle removal of dashboards link', async () => {
            const logic = await insightTestSetup('test-insight', 'updated', [
                {
                    type: ActivityScope.INSIGHT,
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
                'peter removed test-insight from removed'
            )
        })
        const formats = ['png', 'pdf', 'csv']
        formats.map((format) => {
            it(`can handle export of insight to ${format}`, async () => {
                const logic = await insightTestSetup('test insight', 'exported', [
                    {
                        type: ActivityScope.INSIGHT,
                        action: 'exported',
                        field: 'export_format',
                        before: undefined,
                        after: `something/${format}`,
                    },
                ])
                const actual = logic.values.humanizedActivity

                expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                    `exported test insight as a ${format}`
                )
            })
        })
    })
})
