import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { DashboardTemplateChooser } from 'scenes/dashboard/DashboardTemplateChooser'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { DashboardsTable } from 'scenes/dashboard/dashboards/DashboardsTable'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { FeatureFlagType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

export function AnalysisTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <div className="NewDashboardModal">
            <BindLogic logic={newDashboardLogic} props={{ featureFlagId: featureFlag.id as number }}>
                {featureFlag.analytics_dashboards && featureFlag.analytics_dashboards.length > 0 ? (
                    <FeatureFlagDashboardsTableContainer />
                ) : (
                    featureFlag.id && (
                        <>
                            <DashboardTemplateChooser scope="feature_flag" />
                            <NewDashboardModal />
                        </>
                    )
                )}
            </BindLogic>
        </div>
    )
}

function FeatureFlagDashboardsTableContainer(): JSX.Element {
    const { filteredDashboards } = useValues(featureFlagLogic)
    const { showNewDashboardModal } = useActions(newDashboardLogic)

    const { dashboardsLoading } = useValues(dashboardsModel)
    const { filters } = useValues(dashboardsLogic)

    return (
        <>
            <DashboardsTable
                extraActions={
                    <div className="flex items-center gap-2">
                        <LemonButton type="primary" onClick={showNewDashboardModal}>
                            New dashboard
                        </LemonButton>
                    </div>
                }
                hideActions={true}
                dashboards={filteredDashboards}
                dashboardsLoading={dashboardsLoading}
                filters={filters}
            />
            <NewDashboardModal />
        </>
    )
}
