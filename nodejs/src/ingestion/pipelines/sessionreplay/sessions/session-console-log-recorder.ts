import { ConsoleLogLevel } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { ClickHouseTimestamp } from '~/types'

import { ConsoleLogEntry, SessionConsoleLogStore } from './session-console-log-store'

/** One console log event extracted from a message, not yet tied to a session or batch. */
export interface ExtractedConsoleLog {
    level: ConsoleLogLevel
    message: string
    /** ClickHouse-formatted timestamp of the console event. */
    timestamp: ClickHouseTimestamp
}

/**
 * Per-message console log data, precomputed by the extract-console-logs step (business logic).
 * Counts include duplicates; the recorder dedupes entries only for storage.
 */
export interface ExtractedConsoleLogs {
    consoleLogCount: number
    consoleWarnCount: number
    consoleErrorCount: number
    entries: ExtractedConsoleLog[]
}

function deduplicateConsoleLogEntries(consoleLogEntries: ConsoleLogEntry[]): ConsoleLogEntry[] {
    // assuming that the console log entries are all for one team id (and they should be)
    // because we only use these for search
    // then we can deduplicate them by the message string and level

    const seen = new Set<string>()
    const deduped: ConsoleLogEntry[] = []

    for (const cle of consoleLogEntries) {
        const fingerPrint = `${cle.level}-${cle.message}`
        if (!seen.has(fingerPrint)) {
            deduped.push(cle)
            seen.add(fingerPrint)
        }
    }
    return deduped
}

export interface ConsoleLogEndResult {
    /** Number of console log messages */
    consoleLogCount: number
    /** Number of console warning messages */
    consoleWarnCount: number
    /** Number of console error messages */
    consoleErrorCount: number
}

/**
 * Records console log events for a single session recording
 */
export class SessionConsoleLogRecorder {
    private ended = false
    private consoleLogCount: number = 0
    private consoleWarnCount: number = 0
    private consoleErrorCount: number = 0

    constructor(
        public readonly sessionId: string,
        public readonly teamId: number,
        public readonly batchId: string,
        private readonly store: SessionConsoleLogStore
    ) {}

    /**
     * Aggregates one message's precomputed console log data (from the extract-console-logs step) into the
     * session: folds the counts in and stores the entries, stamped with this session's identifiers.
     *
     * @throws If called after end()
     */
    public async recordSessionLogs(logs: ExtractedConsoleLogs): Promise<void> {
        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        this.consoleLogCount += logs.consoleLogCount
        this.consoleWarnCount += logs.consoleWarnCount
        this.consoleErrorCount += logs.consoleErrorCount

        if (logs.entries.length === 0) {
            return
        }

        const logsToStore: ConsoleLogEntry[] = logs.entries.map((entry) => ({
            team_id: this.teamId,
            message: entry.message,
            level: entry.level,
            log_source: 'session_replay',
            log_source_id: this.sessionId,
            instance_id: null,
            timestamp: entry.timestamp,
            batch_id: this.batchId,
        }))

        await this.store.storeSessionConsoleLogs(deduplicateConsoleLogEntries(logsToStore))
    }

    /**
     * Finalizes the console log recording and returns the counts
     *
     * @returns The console log counts
     * @throws If called more than once
     */
    public end(): ConsoleLogEndResult {
        if (this.ended) {
            throw new Error('end() has already been called')
        }
        this.ended = true

        return {
            consoleLogCount: this.consoleLogCount,
            consoleWarnCount: this.consoleWarnCount,
            consoleErrorCount: this.consoleErrorCount,
        }
    }
}
