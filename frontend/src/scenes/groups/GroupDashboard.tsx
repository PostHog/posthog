import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { useEffect } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { groupDashboardLogic } from 'scenes/groups/groupDashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import { Group, GroupPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export function GroupDashboard({ groupData }: { groupData: Group }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Group }))
    const { dashboardLogicProps } = useValues(groupDashboardLogic)

    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps))
    const { setProperties } = useActions(dashboardLogic(dashboardLogicProps))
    useEffect(() => {
        if (dashboard && groupData) {
            // `dashboard?.filters.properties` is typed as `any` but it's a list...
            const current = Array.isArray(dashboard?.filters.properties) ? dashboard?.filters.properties : []

            // TODO need to be able to handle groups that don't have an ID key
            const desired: GroupPropertyFilter = {
                key: 'id',
                value: [groupData.group_properties.id.toString()],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Group,
                group_type_index: groupData.group_type_index,
            }

            const hasFilter = current.some(
                (item) =>
                    item.type === PropertyFilterType.Group &&
                    item.group_type_index === groupData.group_type_index &&
                    item.key === 'id'
            )
            if (!hasFilter) {
                setProperties([...current, desired])
            }
        }
    }, [dashboard, groupData])

    return (
        <>
            {dashboardLogicProps.id !== undefined ? (
                <>
                    <div className="flex items-center justify-end mb-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="group-dashboard-change-dashboard"
                            onClick={showSceneDashboardChoiceModal}
                        >
                            Change dashboard
                        </LemonButton>
                    </div>
                    <Dashboard id={dashboardLogicProps.id.toString()} placement={dashboardLogicProps.placement} />
                </>
            ) : (
                <SceneDashboardChoiceRequired
                    open={() => {
                        showSceneDashboardChoiceModal()
                    }}
                    scene={Scene.Group}
                />
            )}
            <SceneDashboardChoiceModal scene={Scene.Group} />
        </>
    )
}
