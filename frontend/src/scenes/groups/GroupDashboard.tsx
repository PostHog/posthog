import { useActions, useValues } from 'kea'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { Scene } from 'scenes/sceneTypes'
import { Group } from '~/types'
import { groupDashboardLogic } from 'scenes/groups/groupDashboardLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'

export function GroupDashboard({}: { groupData: Group; groupTypeName: string }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Group }))
    const { dashboardLogicProps } = useValues(groupDashboardLogic)

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
