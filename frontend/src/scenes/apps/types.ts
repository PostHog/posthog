export interface AppMetricsUrlParams {
    tab?: AppMetricsTab
    from?: string
    error?: [string, string]
}

export enum AppMetricsTab {
    Logs = 'logs',
    ProcessEvent = 'processEvent',
    OnEvent = 'onEvent',
    ExportEvents = 'exportEvents',
    ScheduledTask = 'scheduledTask',
    HistoricalExports = 'historical_exports',
    History = 'history',
}
