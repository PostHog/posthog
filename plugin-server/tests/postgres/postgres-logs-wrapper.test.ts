import { PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { PostgresLogsWrapper } from '../../src/utils/db/postgres-logs-wrapper'
import { UUIDT } from '../../src/utils/utils'

describe('PostgresLogsWrapper', () => {
    let postgresLogsWrapper: PostgresLogsWrapper
    let db: any

    beforeEach(() => {
        db = {
            queuePluginLogEntry: jest.fn(),
            batchInsertPostgresLogs: jest.fn(),
        } as any
        postgresLogsWrapper = new PostgresLogsWrapper(db)
    })

    test('postgresLogsWrapper adds and flushes logs correctly', async () => {
        jest.useFakeTimers()
        postgresLogsWrapper.logs.push({
            id: new UUIDT().toString(),
            plugin_config_id: 39,
            plugin_id: 60,
            team_id: 2,
            message: 'plugin loaded',
            source: PluginLogEntrySource.System,
            type: PluginLogEntryType.Info,
            instance_id: new UUIDT().toString(),
            timestamp: new Date().toISOString(),
        })
        expect(postgresLogsWrapper.logs.length).toEqual(1)
        await postgresLogsWrapper.flushLogs()
        expect(db.batchInsertPostgresLogs).toHaveBeenCalled()
        expect(postgresLogsWrapper.logs.length).toEqual(0)
        expect(postgresLogsWrapper.flushTimeout).toEqual(null)
    })
})
