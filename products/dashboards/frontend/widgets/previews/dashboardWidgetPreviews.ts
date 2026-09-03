import type { DashboardWidgetCatalogKey } from '../../widget_types/catalog'
import { ActivityEventsWidgetPreview } from './ActivityEventsWidgetPreview'
import { ConversationsWidgetPreview } from './ConversationsWidgetPreview'
import { ErrorTrackingWidgetPreview } from './ErrorTrackingWidgetPreview'
import { ExperimentResultsWidgetPreview, ExperimentsListWidgetPreview } from './ExperimentsWidgetPreviews'
import { LogsWidgetPreview } from './LogsWidgetPreview'
import { SessionReplayWidgetPreview } from './SessionReplayWidgetPreview'
import { SurveyResultsWidgetPreview } from './SurveysWidgetPreviews'

// Kept apart from the catalog: the catalog is imported by dashboardLogic and, through it, by the
// app shell, while the previews render product UI (recordings player, error tracking list, logs)
// that only the add-widget modal needs. Importing them from the catalog put ~1 MiB of product code
// on every logged-in page load.
/** New widget types: add preview components here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_PREVIEWS: Record<DashboardWidgetCatalogKey, () => JSX.Element> = {
    conversations_recent_tickets: ConversationsWidgetPreview,
    activity_events_list: ActivityEventsWidgetPreview,
    error_tracking_list: ErrorTrackingWidgetPreview,
    session_replay_list: SessionReplayWidgetPreview,
    experiments_list: ExperimentsListWidgetPreview,
    experiment_results: ExperimentResultsWidgetPreview,
    survey_results: SurveyResultsWidgetPreview,
    logs_list: LogsWidgetPreview,
}
