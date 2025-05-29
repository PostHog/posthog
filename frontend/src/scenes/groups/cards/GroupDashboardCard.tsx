import { useActions, useValues } from 'kea'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect, useState } from 'react'
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

    return <Dashboard id={groupTypeDetailDashboard.toString()} placement={DashboardPlacement.Group} />
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
            <div className="flex justify-end">
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
        </div>
    )
}
