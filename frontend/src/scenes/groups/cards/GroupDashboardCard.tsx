import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { groupLogic } from 'scenes/groups/groupLogic'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement, Group, PropertyFilterType, PropertyOperator } from '~/types'

function GroupDetailDashboard({
    groupTypeDetailDashboard,
    groupData,
}: {
    groupTypeDetailDashboard: number
    groupData: Group
}): JSX.Element {
    const { groupTypeName } = useValues(groupLogic)
    const { setProperties, setLoadLayoutFromServerOnPreview } = useActions(
        dashboardLogic({ id: groupTypeDetailDashboard })
    )

    useEffect(() => {
        if (groupTypeDetailDashboard && groupData) {
            setLoadLayoutFromServerOnPreview(true)
            setProperties([
                {
                    type: PropertyFilterType.EventMetadata,
                    key: `$group_${groupData.group_type_index}`,
                    label: groupTypeName,
                    value: groupData.group_key,
                    operator: PropertyOperator.Exact,
                },
            ])
        }
    }, [groupTypeDetailDashboard, groupData, groupTypeName, setProperties, setLoadLayoutFromServerOnPreview])

    return (
        <div className="flex flex-col gap-0">
            <h2>Insights</h2>
            <Dashboard id={groupTypeDetailDashboard.toString()} placement={DashboardPlacement.Group} />
        </div>
    )
}

export function GroupDashboardCard(): JSX.Element {
    const { groupData, groupTypeDetailDashboard, groupTypeName } = useValues(groupLogic)

    const { createDetailDashboard } = useActions(groupLogic)
    const { reportGroupTypeDetailDashboardCreated } = useActions(eventUsageLogic)
    const [creatingDetailDashboard, setCreatingDetailDashboard] = useState(false)

    if (!groupData) {
        return <></>
    }

    if (groupTypeDetailDashboard) {
        return <GroupDetailDashboard groupTypeDetailDashboard={groupTypeDetailDashboard} groupData={groupData} />
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-row justify-between items-center">
                <h2>Insights</h2>
                <LemonButton
                    type="secondary"
                    disabled={creatingDetailDashboard}
                    onClick={() => {
                        setCreatingDetailDashboard(true)
                        reportGroupTypeDetailDashboardCreated()
                        createDetailDashboard(groupData.group_type_index)
                    }}
                >
                    Customize
                </LemonButton>
            </div>
            <div className="grid grid-cols-2 gap-2">
                <QueryCard
                    title="Top paths"
                    description={`Shows the most popular pages viewed by this ${groupTypeName} in the last 30 days`}
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
                                            {
                                                key: `$group_${groupData.group_type_index}`,
                                                value: groupData.group_key,
                                                operator: PropertyOperator.Exact,
                                            },
                                        ],
                                        math: 'unique_session',
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
                    context={{ refresh: 'force_blocking' }}
                />
                <QueryCard
                    title="Top events"
                    description={`Shows the most popular events by this ${groupTypeName} in the last 30 days`}
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
                                        properties: [
                                            {
                                                key: `$group_${groupData.group_type_index}`,
                                                value: groupData.group_key,
                                                operator: PropertyOperator.Exact,
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
                    context={{ refresh: 'force_blocking' }}
                />
                <QueryCard
                    title="Weekly active users"
                    description={`Shows the number of unique users from this ${groupTypeName} in the last 90 days`}
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
                                        math: 'dau',
                                        event: null,
                                        properties: [
                                            {
                                                key: `$group_${groupData.group_type_index}`,
                                                value: groupData.group_key,
                                                operator: PropertyOperator.Exact,
                                            },
                                        ],
                                    },
                                ],
                            },
                        } as Node
                    }
                    context={{ refresh: 'force_blocking' }}
                />
                <QueryCard
                    title="Monthly active users"
                    description={`Shows the number of unique users from this ${groupTypeName} in the last year`}
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
                                        math: 'dau',
                                        event: null,
                                        properties: [
                                            {
                                                key: `$group_${groupData.group_type_index}`,
                                                value: groupData.group_key,
                                                operator: PropertyOperator.Exact,
                                            },
                                        ],
                                    },
                                ],
                            },
                        } as Node
                    }
                    context={{ refresh: 'force_blocking' }}
                />
            </div>
            <div className="grid grid-cols-1 gap-2">
                <QueryCard
                    title="Retained users"
                    description={`Shows the number of users from this ${groupTypeName} who returned 12 weeks after their first visit`}
                    query={
                        {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.RetentionQuery,
                                retentionFilter: {
                                    period: 'Week',
                                    targetEntity: {
                                        id: '$pageview',
                                        name: '$pageview',
                                        type: 'events',
                                    },
                                    retentionType: 'retention_first_time',
                                    totalIntervals: 12,
                                    returningEntity: {
                                        id: '$pageview',
                                        name: '$pageview',
                                        type: 'events',
                                    },
                                    meanRetentionCalculation: 'simple',
                                },
                                properties: {
                                    type: 'AND',
                                    values: [
                                        {
                                            type: 'AND',
                                            values: [
                                                {
                                                    type: 'hogql',
                                                    key: `$group_${groupData.group_type_index}='${groupData.group_key}'`,
                                                    value: null,
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                            full: true,
                        } as Node
                    }
                    context={{ refresh: 'force_blocking' }}
                />
            </div>
        </div>
    )
}
