import { AppMetricsTab } from './appMetricsSceneLogic'

export const DescriptionColumns: Record<
    AppMetricsTab,
    { success: string; success_on_retry?: string; failure: string }
> = {
    [AppMetricsTab.ProcessEvent]: {
        success: 'Events processed',
        failure: 'Failed events',
    },
    [AppMetricsTab.OnEvent]: {
        success: 'Events processed',
        success_on_retry: 'Events processed on retry',
        failure: 'Failed events',
    },
    [AppMetricsTab.ExportEvents]: {
        success: 'Events delivered',
        success_on_retry: 'Events delivered on retry',
        failure: 'Failed events',
    },
    [AppMetricsTab.HistoricalExports]: {
        success: 'Events delivered',
        success_on_retry: 'Events delivered on retry',
        failure: 'Failed events',
    },
}
