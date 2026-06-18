import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardsGrid } from './DashboardsGrid'
import { resolveDashboardsListViewVariant } from './dashboardsListViewVariants'
import { DashboardsTableContainer } from './DashboardsTable'

// Routes the dashboards list body to the arm selected by the dashboards-list-view experiment flag.
// Control renders today's table unchanged; finder falls back to the table until the finder arm ships.
export function DashboardsContent(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant = resolveDashboardsListViewVariant(featureFlags)

    if (variant === 'grid') {
        return <DashboardsGrid />
    }
    return <DashboardsTableContainer />
}
