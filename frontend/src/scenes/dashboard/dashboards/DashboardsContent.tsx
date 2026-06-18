import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardsExplorer } from './DashboardsExplorer'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'
import { DashboardsTableContainer } from './DashboardsTable'
import { DashboardsTree } from './DashboardsTree'

// Routes the dashboards list body to the arm selected by the dashboards-list-view experiment flag.
// Control (and any unknown value) renders today's table unchanged; the two treatment arms are two
// folder-navigation paradigms — explorer (drill-in) and tree (persistent folder tree).
export function DashboardsContent(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant = resolveDashboardsListViewVariant(featureFlags)

    if (variant === 'explorer') {
        return <DashboardsExplorer />
    }
    if (variant === 'tree') {
        return <DashboardsTree />
    }
    return <DashboardsTableContainer />
}
