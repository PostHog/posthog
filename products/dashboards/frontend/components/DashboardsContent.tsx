import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardsTableContainer } from 'scenes/dashboard/dashboards/DashboardsTable'

import { resolveDashboardsListViewVariant } from '../logics/dashboardsListViewVariants'
import { DashboardsTree } from './DashboardsTree'

// Routes the dashboards list body to the arm selected by the dashboards-list-view experiment flag.
// Control (and any unknown value) renders today's table unchanged; the tree treatment arm shows a
// persistent folder-tree panel beside the table.
export function DashboardsContent(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant = resolveDashboardsListViewVariant(featureFlags)

    if (variant === 'tree') {
        return <DashboardsTree />
    }
    return <DashboardsTableContainer />
}
