import { DateTime } from 'luxon'

import { TimestampFormat } from '../../../../types'
import { castTimestampOrNow } from '../../../../utils/utils'
import { ParsedMessageData } from '../kafka/types'
import { ConsoleLogLevel, getConsoleLogLevel } from '../rrweb-types'
import { ConsoleLogEntry, SessionConsoleLogStore } from './session-console-log-store'

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
                const logLevel = getConsoleLogLevel(event)
                if (!logLevel) {
                    continue
                }

                if (logLevel === ConsoleLogLevel.Log) {
                    this.consoleLogCount++
                } else if (logLevel === ConsoleLogLevel.Warn) {
                    this.consoleWarnCount++
                } else if (logLevel === ConsoleLogLevel.Error) {
                    this.consoleErrorCount++
                }

                const eventData = event.data as { plugin?: unknown; payload?: { payload?: unknown } } | undefined
                if (event.type === 6 && eventData?.plugin === 'rrweb/console@1') {
                    const level = logLevel === ConsoleLogLevel.Log ? 'info' : logLevel.toLowerCase()
                    const maybePayload = eventData?.payload?.payload
                    const payload: unknown[] = Array.isArray(maybePayload) ? maybePayload : []
                    const message = payloadToSafeString(payload)

                    logsToStore.push({
                        team_id: this.teamId,
                        message,
                        level: level as any,
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
            await this.store.storeSessionConsoleLogs(logsToStore)
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
