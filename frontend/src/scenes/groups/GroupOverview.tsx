import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect, useState } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { groupLogic } from 'scenes/groups/groupLogic'

import { DashboardPlacement, Group, PropertyFilterType, PropertyOperator } from '~/types'

function GroupOverviewDashboard({
    groupTypeDetailDashboard,
    groupData,
}: {
    groupTypeDetailDashboard: number
    groupData: Group
}): JSX.Element {
    const { setProperties } = useActions(dashboardLogic({ id: groupTypeDetailDashboard }))

    useEffect(() => {
        if (groupTypeDetailDashboard && groupData) {
            setProperties([
                {
                    type: PropertyFilterType.EventMetadata,
                    key: `$group_${groupData.group_type_index}`,
                    value: groupData.group_key,
                    operator: PropertyOperator.Exact,
                },
            ])
        }
    }, [groupTypeDetailDashboard, groupData, setProperties])

    return <Dashboard id={groupTypeDetailDashboard.toString()} placement={DashboardPlacement.Group} />
}

export function GroupOverview(): JSX.Element {
    const { groupTypeName, groupData, groupTypeDetailDashboard } = useValues(groupLogic)

    const { createDetailDashboard } = useActions(groupLogic)
    const { reportGroupTypeDetailDashboardCreated } = useActions(eventUsageLogic)
    const [creatingDetailDashboard, setCreatingDetailDashboard] = useState(false)

    if (!groupData) {
        return <></>
    }

    if (groupTypeDetailDashboard) {
        return <GroupOverviewDashboard groupTypeDetailDashboard={groupTypeDetailDashboard} groupData={groupData} />
    }

    return (
        <div className="border-2 border-dashed border-primary w-full p-8 justify-center rounded mt-2 mb-4">
            <div className="flex items-center gap-8 w-full justify-center">
                <div className="flex-shrink max-w-140">
                    <h2>No {groupTypeName} dashboard yet</h2>
                    <p className="ml-0">
                        Create a standard dashboard to use with each {groupTypeName} to see weekly active users, most
                        used features, and more.
                    </p>
                    <div className="flex items-center gap-x-4 gap-y-2 mt-6">
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                setCreatingDetailDashboard(true)
                                reportGroupTypeDetailDashboardCreated()
                                createDetailDashboard(groupData.group_type_index)
                            }}
                            disabled={creatingDetailDashboard}
                        >
                            Generate dashboard
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}
