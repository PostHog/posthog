export const capabilitiesInfo: Record<string, string> = {
    processEvent: 'Read + modify access to events before ingestion',
    processEventBatch: 'Read + modify access to events before ingestion, in batches',
    onEvent: 'Read-only access to events',
    exportEvents: 'Read-only access to events, optimized for export',
    runEveryMinute: 'Runs a task every minute',
    runEveryHour: 'Runs a task every hour',
    runEveryDay: 'Runs a task every day',
}
