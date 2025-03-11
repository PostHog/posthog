import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { ClickHouseTimestamp, LogLevel } from '../../../../types'
import { status } from '../../../../utils/status'

export type ConsoleLogEntry = {
    team_id: number
    message: string
    level: LogLevel
    log_source: 'session_replay'
    log_source_id: string
    instance_id: string | null
    timestamp: ClickHouseTimestamp
    batch_id: string
}

export class SessionConsoleLogStore {
    constructor(private producer: KafkaProducerWrapper) {
        status.debug('🔍', 'session_console_log_store_created')
    }

    public async storeSessionConsoleLogs(logs: ConsoleLogEntry[]): Promise<void> {
        status.info('🔍', 'session_console_log_store_storing_logs', { count: logs.length })
        // TODO: Implement storing console logs to Kafka
        return Promise.resolve()
    }
}
