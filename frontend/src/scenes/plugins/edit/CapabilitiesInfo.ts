export const capabilitiesInfo: Record<string, string> = {
    processEvent: 'Used to read and modify events before ingestion',
    processEventBatch: 'Used to read and modify and modify events in batches before ingestion',
    onEvent: 'Provides read-only access to events',
    onSnapshot: 'Provides read-only access to session recording events',
    exportEvents: 'Provides a way to easily export events to any destination',
    runEveryMinute: 'Runs a task every minute',
    runEveryHour: 'Runs a task every hour',
    runEveryDay: 'Runs a task every day',
}
