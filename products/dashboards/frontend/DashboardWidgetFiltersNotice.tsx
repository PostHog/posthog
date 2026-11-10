import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { DashboardWidgetRunResultApi } from './generated/api.schemas'

/** Whether a dashboard filter changed the query of any widget shown. Reads `dashboard_filters_applied`, which
 * run_widgets sets from WidgetDashboardFilters.is_applied in products/dashboards/backend/widgets/dashboard_filters.py. */
export function dashboardFiltersChangeWidgets(results: Record<number, DashboardWidgetRunResultApi>): boolean {
    return Object.values(results).some((result) => !result.error && !!result.dashboard_filters_applied)
}

// Remove after 2027-02-10, once people who use dashboard filters with widgets have had a full quarter to see it.
export function DashboardWidgetFiltersNotice(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { widgetResultsByTileId } = useValues(dashboardLogic)

    if (
        !featureFlags[FEATURE_FLAGS.DASHBOARD_WIDGET_FILTERS_NOTICE] ||
        !dashboardFiltersChangeWidgets(widgetResultsByTileId)
    ) {
        return null
    }

    return (
        <LemonBanner type="info" className="mt-4 mb-2" dismissKey="dashboard-widget-filters-notice">
            Dashboard filters now apply to widget tiles too: the dashboard date range, test account filter, and property
            filters replace or narrow each widget's own. Widget results may differ from before.
        </LemonBanner>
    )
}
