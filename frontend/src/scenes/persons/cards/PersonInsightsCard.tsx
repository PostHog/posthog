import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { PersonType } from '~/types'

export function PersonInsightsCard({ person }: { person: PersonType }): JSX.Element {
    // Helper function to create person-specific query context
    const getPersonQueryContext = (): { personId: string; refresh: 'force_blocking' } => ({
        personId: person.uuid!,
        refresh: 'force_blocking' as const,
    })

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-2">
                <QueryCard
                    title="Top paths"
                    description="Shows the most popular pages viewed by this person in the last 30 days"
                    query={
                        {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        event: '$pageview',
                                        name: '$pageview',
                                        properties: [
                                            {
                                                key: '$pathname',
                                                value: ['/'],
                                                operator: 'is_not',
                                                type: 'event',
                                            },
                                        ],
                                        math: 'total',
                                    },
                                ],
                                trendsFilter: {
                                    display: 'ActionsBarValue',
                                },
                                breakdownFilter: {
                                    breakdowns: [
                                        {
                                            property: '$pathname',
                                            type: 'event',
                                            normalize_url: true,
                                        },
                                    ],
                                },
                                dateRange: {
                                    date_from: '-30d',
                                    date_to: null,
                                    explicitDate: false,
                                },
                                interval: 'day',
                            },
                            full: true,
                        } as Node
                    }
                    context={getPersonQueryContext()}
                />
                <QueryCard
                    title="Top events"
                    description="Shows the most popular events by this person in the last 30 days"
                    query={
                        {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        event: null,
                                        name: 'All events',
                                        properties: [],
                                        math: 'total',
                                    },
                                ],
                                trendsFilter: {
                                    display: 'ActionsBarValue',
                                },
                                breakdownFilter: {
                                    breakdowns: [
                                        {
                                            property: 'event',
                                            type: 'event_metadata',
                                        },
                                    ],
                                },
                                dateRange: {
                                    date_from: '-30d',
                                    date_to: null,
                                    explicitDate: false,
                                },
                                interval: 'day',
                            },
                            full: true,
                        } as Node
                    }
                    context={getPersonQueryContext()}
                />
                <QueryCard
                    title="Weekly activity"
                    description="Shows this person's activity over the last 90 days"
                    query={
                        {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                interval: 'week',
                                dateRange: {
                                    date_from: '-90d',
                                },
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        math: 'total',
                                        event: null,
                                        properties: [],
                                    },
                                ],
                            },
                        } as Node
                    }
                    context={getPersonQueryContext()}
                />
                <QueryCard
                    title="Monthly activity"
                    description="Shows this person's activity over the last year"
                    query={
                        {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                interval: 'month',
                                dateRange: {
                                    date_from: '-365d',
                                },
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        math: 'total',
                                        event: null,
                                        properties: [],
                                    },
                                ],
                            },
                        } as Node
                    }
                    context={getPersonQueryContext()}
                />
            </div>
        </div>
    )
}
