import { DateTime } from 'luxon'

import { sanitizeForUTF8 } from '~/common/utils/strings'
import { castTimestampOrNow } from '~/common/utils/utils'
import { ConsoleLogLevel, RRWebEventType } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { MessageWithTeam } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { ClickHouseTimestamp, TimestampFormat } from '~/types'

import { ConsoleLogEntry, SessionConsoleLogStore } from './session-console-log-store'

const levelMapping: Record<string, ConsoleLogLevel> = {
    info: ConsoleLogLevel.Info,
    count: ConsoleLogLevel.Info,
    timeEnd: ConsoleLogLevel.Info,
    warn: ConsoleLogLevel.Warn,
    countReset: ConsoleLogLevel.Warn,
    error: ConsoleLogLevel.Error,
    assert: ConsoleLogLevel.Error,
    // really these should be 'info' but we don't want users to have to think about this
    log: ConsoleLogLevel.Info,
    trace: ConsoleLogLevel.Info,
    dir: ConsoleLogLevel.Info,
    dirxml: ConsoleLogLevel.Info,
    group: ConsoleLogLevel.Info,
    groupCollapsed: ConsoleLogLevel.Info,
    debug: ConsoleLogLevel.Info,
    timeLog: ConsoleLogLevel.Info,
}

function safeLevel(level: unknown): ConsoleLogLevel {
    return levelMapping[typeof level === 'string' ? level : 'info'] || ConsoleLogLevel.Info
}

function payloadToSafeString(payload: unknown[]): string {
    // the individual strings are sometimes wrapped in quotes... we want to strip those
    return payload
        .filter((item: unknown): item is string => !!item && typeof item === 'string')
        .map((item) => sanitizeForUTF8(item.substring(0, 2999)))
        .join(' ')
}

/** One console log event extracted from a message, not yet tied to a session or batch. */
export interface ExtractedConsoleLog {
    level: ConsoleLogLevel
    message: string
    /** ClickHouse-formatted timestamp of the console event. */
    timestamp: ClickHouseTimestamp
}

/**
 * Per-message console log data, precomputed by the serialize reduce step (business logic).
 * Counts include duplicates; the recorder dedupes entries only for storage.
 */
export interface ExtractedConsoleLogs {
    consoleLogCount: number
    consoleWarnCount: number
    consoleErrorCount: number
    entries: ExtractedConsoleLog[]
}

/**
 * Extracts the console log events from one parsed message: the level counts plus the entries to
 * store. Respects the team's console log ingestion setting and handles the native anonymizer's
 * pre-serialized fast path, which carries level counts in its metadata and no entries.
 */
export function extractConsoleLogs(message: MessageWithTeam): ExtractedConsoleLogs {
    const extracted: ExtractedConsoleLogs = {
        consoleLogCount: 0,
        consoleWarnCount: 0,
        consoleErrorCount: 0,
        entries: [],
    }

    if (!message.team.consoleLogIngestionEnabled) {
        return extracted
    }

    if (message.message.preSerialized) {
        const { consoleLogCount, consoleWarnCount, consoleErrorCount } = message.message.preSerialized
        extracted.consoleLogCount = consoleLogCount
        extracted.consoleWarnCount = consoleWarnCount
        extracted.consoleErrorCount = consoleErrorCount
        return extracted
    }

    for (const events of Object.values(message.message.eventsByWindowId)) {
        for (const event of events) {
            const eventData = event.data as
                | { plugin?: unknown; payload?: { payload?: unknown; level?: unknown } }
                | undefined
            if (event.type === RRWebEventType.Plugin && eventData?.plugin === 'rrweb/console@1') {
                const timestamp = DateTime.fromMillis(event.timestamp)
                const level = safeLevel(eventData?.payload?.level)
                const maybePayload = eventData?.payload?.payload
                const payload: unknown[] = Array.isArray(maybePayload) ? maybePayload : []

                if (level === ConsoleLogLevel.Info) {
                    extracted.consoleLogCount++
                } else if (level === ConsoleLogLevel.Warn) {
                    extracted.consoleWarnCount++
                } else if (level === ConsoleLogLevel.Error) {
                    extracted.consoleErrorCount++
                }

                extracted.entries.push({
                    level,
                    message: payloadToSafeString(payload),
                    timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
                })
            }
        }
    }

    return extracted
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
     * Aggregates one message's precomputed console log data ({@link extractConsoleLogs}) into the
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
