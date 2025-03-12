import { DateTime } from 'luxon'

import { LogLevel, TimestampFormat } from '../../../../types'
import { castTimestampOrNow } from '../../../../utils/utils'
import { ParsedMessageData } from '../kafka/types'
import { RRWebEventType } from '../rrweb-types'
import { ConsoleLogEntry, SessionConsoleLogStore } from './session-console-log-store'

const levelMapping: Record<string, LogLevel> = {
    info: LogLevel.Info,
    count: LogLevel.Info,
    timeEnd: LogLevel.Info,
    warn: LogLevel.Warn,
    countReset: LogLevel.Warn,
    error: LogLevel.Error,
    assert: LogLevel.Error,
    // really these should be 'log' but we don't want users to have to think about this
    log: LogLevel.Info,
    trace: LogLevel.Info,
    dir: LogLevel.Info,
    dirxml: LogLevel.Info,
    group: LogLevel.Info,
    groupCollapsed: LogLevel.Info,
    debug: LogLevel.Info,
    timeLog: LogLevel.Info,
}

function safeLevel(level: unknown): LogLevel {
    return levelMapping[typeof level === 'string' ? level : 'info'] || LogLevel.Info
}

function sanitizeForUTF8(input: string): string {
    // the JS console truncates some logs...
    // when it does that it doesn't check if the output is valid UTF-8
    // and so it can truncate halfway through a UTF-16 pair 🤷
    // the simplest way to fix this is to convert to a buffer and back
    // annoyingly Node 20 has `toWellFormed` which might have been useful
    const buffer = Buffer.from(input)
    return buffer.toString()
}

function payloadToSafeString(payload: unknown[]): string {
    // the individual strings are sometimes wrapped in quotes... we want to strip those
    return payload
        .filter((item: unknown): item is string => !!item && typeof item === 'string')
        .map((item) => sanitizeForUTF8(item.substring(0, 2999)))
        .join(' ')
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
     * Records a message containing events for this session
     * Events are buffered until end() is called
     *
     * @param message - Message containing events for one or more windows
     * @throws If called after end()
     */
    public async recordMessage(message: ParsedMessageData): Promise<void> {
        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        const logsToStore: ConsoleLogEntry[] = []

        for (const events of Object.values(message.eventsByWindowId)) {
            for (const event of events) {
                const eventData = event.data as
                    | { plugin?: unknown; payload?: { payload?: unknown; level?: unknown } }
                    | undefined
                if (event.type === RRWebEventType.Plugin && eventData?.plugin === 'rrweb/console@1') {
                    const level = safeLevel(eventData?.payload?.level)
                    const maybePayload = eventData?.payload?.payload
                    const payload: unknown[] = Array.isArray(maybePayload) ? maybePayload : []
                    const message = payloadToSafeString(payload)

                    if (level === 'info') {
                        this.consoleLogCount++
                    } else if (level === 'warn') {
                        this.consoleWarnCount++
                    } else if (level === 'error') {
                        this.consoleErrorCount++
                    }

                    logsToStore.push({
                        team_id: this.teamId,
                        message,
                        level,
                        log_source: 'session_replay',
                        log_source_id: this.sessionId,
                        instance_id: null,
                        timestamp: castTimestampOrNow(DateTime.fromMillis(event.timestamp), TimestampFormat.ClickHouse),
                        batch_id: this.batchId,
                    })
                }
            }
        }

        if (logsToStore.length > 0) {
            await this.store.storeSessionConsoleLogs(deduplicateConsoleLogEntries(logsToStore))
        }
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
