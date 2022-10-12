import { AppMetricsTab } from './appMetricsSceneLogic'

export const DescriptionColumns: Record<
    AppMetricsTab,
    { successes: string; successes_on_retry?: string; failures: string }
> = {
    [AppMetricsTab.ProcessEvent]: {
        successes: 'Events processed',
        failures: 'Failed events',
    },
    [AppMetricsTab.OnEvent]: {
        successes: 'Events processed',
        successes_on_retry: 'Events processed on retry',
        failures: 'Failed events',
    },
    [AppMetricsTab.ExportEvents]: {
        successes: 'Events delivered',
        successes_on_retry: 'Events delivered on retry',
        failures: 'Failed events',
    },
    [AppMetricsTab.HistoricalExports]: {
        successes: 'Events delivered',
        successes_on_retry: 'Events delivered on retry',
        failures: 'Failed events',
    },
}
