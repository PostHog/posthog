import type { FilterSpec } from '../../filters/filterSpec'
import { type PanelTypeSpec, sizeOfPanels } from '../../panels/core/panelSpec'
import { settleDashboard } from '../edits/dashboardEdits'
import type { Dashboard } from './dashboardTypes'
import { loadDashboard } from './sharedPanels'
import { type DashboardProblem, isDashboardDocument, validateDashboard } from './validateDashboard'

export type DashboardFromJson = {
    /** Null when the document does not have the shape of a dashboard, so nothing can render. */
    dashboard: Dashboard | null
    problems: DashboardProblem[]
}

/**
 * Turns a dashboard document, such as JSON a product writes or a board's spec, into what `DashboardView` renders. A
 * panel that fails its own type's check still loads, and its tile says why, so one broken panel never hides the rest.
 */
export function dashboardFromJson(
    json: unknown,
    panels: PanelTypeSpec[],
    filters: FilterSpec[] = []
): DashboardFromJson {
    const problems = validateDashboard(json, panels, filters)
    if (!isDashboardDocument(json)) {
        return { dashboard: null, problems }
    }
    return { dashboard: settleDashboard(loadDashboard(json), sizeOfPanels(panels)), problems }
}
