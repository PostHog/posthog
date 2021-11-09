import { determineNodeEnv, NodeEnv } from '../utils'
import { DB, ParsedLogEntry } from './db'

const POSTGRES_LOGS_FLUSH_TIMEOUT_MS = 1000

export class PostgresLogsWrapper {
    logs: ParsedLogEntry[]
    flushTimeout: NodeJS.Timeout | null
    db: DB

    constructor(db: DB) {
        this.db = db
        this.logs = []
        this.flushTimeout = null
    }

    async addLog(log: ParsedLogEntry): Promise<void> {
        this.logs.push(log)

        // Flush logs immediately on tests
        if (determineNodeEnv() === NodeEnv.Test) {
            await this.flushLogs()
            return
        }

        if (!this.flushTimeout) {
            this.flushTimeout = setTimeout(async () => {
                await this.flushLogs()
            }, POSTGRES_LOGS_FLUSH_TIMEOUT_MS)
        }
    }

    async flushLogs(): Promise<void> {
        if (this.flushTimeout) {
            clearTimeout(this.flushTimeout)
            this.flushTimeout = null
        }
        if (this.logs.length > 0) {
            await this.db.batchInsertPostgresLogs(this.logs)
            this.logs = []
        }
    }
}
