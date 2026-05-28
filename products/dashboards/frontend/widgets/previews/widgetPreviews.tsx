import type { DashboardWidgetCatalogKey } from '../../widget_types/catalog'

import { ErrorTrackingWidgetPreview } from './ErrorTrackingWidgetPreview'

/** New widget types: add here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_PREVIEWS: Record<DashboardWidgetCatalogKey, () => JSX.Element> = {
    error_tracking_list: ErrorTrackingWidgetPreview,
}
