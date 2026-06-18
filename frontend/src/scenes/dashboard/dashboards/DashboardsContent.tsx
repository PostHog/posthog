import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardsFinder } from './DashboardsFinder'
import { DashboardsGrid } from './DashboardsGrid'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'
import { DashboardsTableContainer } from './DashboardsTable'

// Routes the dashboards list body to the arm selected by the dashboards-list-view experiment flag.
// Control (and any unknown value) renders today's table unchanged.
export function DashboardsContent(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant = resolveDashboardsListViewVariant(featureFlags)

    if (variant === 'grid') {
        return <DashboardsGrid />
    }
    if (variant === 'finder') {
        return <DashboardsFinder />
    }
    return <DashboardsTableContainer />
}
