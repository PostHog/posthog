import { BindLogic, useActions, useValues } from 'kea'
import { DashboardTemplateChooser, NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { DashboardsTable } from 'scenes/dashboard/dashboards/DashboardsTable'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FeatureFlagType } from '~/types'
import { featureFlagLogic } from './featureFlagLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'

export function AnalysisTab({ featureFlag }: { id: string; featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <div className="NewDashboardModal">
            {featureFlag.dashboards && featureFlag.dashboards.length > 0 ? (
                <FeatureFlagDashboardsTableContainer featureFlag={featureFlag} />
            ) : (
                featureFlag.id && <DashboardTemplateChooser scope="feature_flag" featureFlagId={featureFlag.id} />
            )}
        </div>
    )
}

function FeatureFlagDashboardsTableContainer({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { filteredDashboards } = useValues(featureFlagLogic)
    const _newDashboardLogic = newDashboardLogic({ featureFlagId: featureFlag.id as number })
    const { showNewDashboardModal } = useActions(_newDashboardLogic)

    const { dashboardsLoading } = useValues(dashboardsModel)
    const { filters } = useValues(dashboardsLogic)

    return (
        <>
            <BindLogic logic={deleteDashboardLogic} props={{ featureFlagId: featureFlag.id as number }}>
                <DashboardsTable
                    extraActions={
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    showNewDashboardModal()
                                }}
                            >
                                New Dashboard
                            </LemonButton>
                        </div>
                    }
                    hideActions={true}
                    dashboards={filteredDashboards}
                    dashboardsLoading={dashboardsLoading}
                    filters={filters}
                />
            </BindLogic>
            <NewDashboardModal featureFlag={featureFlag} />
        </>
    )
}
