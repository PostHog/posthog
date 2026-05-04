import { LOG_ENTRIES_OUTPUT, LogEntriesOutput } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import { ClickHouseTimestamp } from '../../types'
import { logger } from '../../utils/logger'
import { ConsoleLogLevel } from '../rrweb-types'
import { SessionBatchMetrics } from './metrics'

export type ConsoleLogEntry = {
    team_id: number
    message: string
    level: ConsoleLogLevel
    log_source: 'session_replay'
    log_source_id: string
    instance_id: string | null
    timestamp: ClickHouseTimestamp
    batch_id: string
}

export class SessionConsoleLogStore {
    private consoleLogsCount = 0
    private pendingMessages: ConsoleLogEntry[] = []
    private readonly messageLimit: number

    constructor(
        private readonly outputs: IngestionOutputs<LogEntriesOutput>,
        options: { messageLimit: number }
    ) {
        this.messageLimit = options.messageLimit
        logger.debug('session_console_log_store_created')
    }

    public async storeSessionConsoleLogs(logs: ConsoleLogEntry[]): Promise<void> {
        if (logs.length === 0) {
            return
        }

        this.pendingMessages.push(...logs)
        this.consoleLogsCount += logs.length

        logger.debug(`stored ${logs.length} console logs for session ${logs[0].log_source_id}`)
        SessionBatchMetrics.incrementConsoleLogsStored(logs.length)

        if (this.pendingMessages.length < this.messageLimit) {
            return
        }
        return this.sync()
    }

    public async flush(): Promise<void> {
        logger.info(`flushing ${this.consoleLogsCount} console logs`)
        await this.sync()
        this.consoleLogsCount = 0
    }

    private async sync(): Promise<void> {
        if (this.pendingMessages.length === 0) {
            return
        }

        logger.debug(`syncing ${this.pendingMessages.length} console log messages`)

        const messages = this.pendingMessages.map((log) => ({
            value: Buffer.from(JSON.stringify(log)),
            key: log.log_source_id,
        }))
        this.pendingMessages = []

        // queueMessages awaits delivery acks for every message, so no separate flush is needed
        // to guarantee messages are on Kafka before the batch offset is committed.
        await this.outputs.queueMessages(LOG_ENTRIES_OUTPUT, messages)
    }
}
