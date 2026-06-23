import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardsExplorer } from './DashboardsExplorer'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'
import { DashboardsTableContainer } from './DashboardsTable'

// Routes the dashboards list body to the arm selected by the dashboards-list-view experiment flag.
// Control (and any unknown value) renders today's table unchanged; the explorer treatment arm is a
// drill-in folder-navigation paradigm.
export function DashboardsContent(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant = resolveDashboardsListViewVariant(featureFlags)

    if (variant === 'explorer') {
        return <DashboardsExplorer />
    }
    return <DashboardsTableContainer />
}
