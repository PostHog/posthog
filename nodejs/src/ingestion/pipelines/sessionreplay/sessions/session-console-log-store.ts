import { LOG_ENTRIES_OUTPUT, LogEntriesOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { clickHouseTimestampToDateTime } from '~/common/utils/utils'
import { ConsoleLogLevel } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { InternalLogEntry, InternalLogsProducer } from '~/logs/internal-logs-producer'
import { ClickHouseTimestamp } from '~/types'

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

    private readonly enabled: boolean
    private readonly internalLogsProducer?: InternalLogsProducer

    constructor(
        private readonly outputs: IngestionOutputs<LogEntriesOutput>,
        options: { messageLimit: number; enabled?: boolean; internalLogsProducer?: InternalLogsProducer }
    ) {
        this.messageLimit = options.messageLimit
        this.enabled = options.enabled ?? true
        this.internalLogsProducer = options.internalLogsProducer
        logger.debug('session_console_log_store_created')
    }

    public async storeSessionConsoleLogs(logs: ConsoleLogEntry[]): Promise<void> {
        if (!this.enabled || logs.length === 0) {
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

        // Only starts the sends, and the catch makes sure a producer bug can never stop the log_entries write below.
        const producer = this.internalLogsProducer
        if (producer) {
            try {
                const entries = this.pendingMessages.filter((log) => producer.accepts(log.team_id))
                producer.enqueue('session_replay', entries.map(toInternalLogEntry))
                producer.flush()
            } catch (error) {
                captureException(error)
            }
        }

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

function toInternalLogEntry(log: ConsoleLogEntry): InternalLogEntry {
    return {
        team_id: log.team_id,
        log_source_id: log.log_source_id,
        instance_id: log.instance_id ?? '',
        timestamp: clickHouseTimestampToDateTime(log.timestamp),
        level: log.level,
        message: log.message,
    }
}
