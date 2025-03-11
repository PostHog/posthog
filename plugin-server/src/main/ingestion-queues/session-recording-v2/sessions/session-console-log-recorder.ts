import { ParsedMessageData } from '../kafka/types'
import { ConsoleLogLevel, getConsoleLogLevel } from '../rrweb-types'

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

    constructor(public readonly sessionId: string, public readonly teamId: number, public readonly batchId: string) {}

    /**
     * Records a message containing events for this session
     * Events are buffered until end() is called
     *
     * @param message - Message containing events for one or more windows
     * @throws If called after end()
     */
    public recordMessage(message: ParsedMessageData): void {
        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        for (const events of Object.values(message.eventsByWindowId)) {
            for (const event of events) {
                const logLevel = getConsoleLogLevel(event)
                if (logLevel === ConsoleLogLevel.Log) {
                    this.consoleLogCount++
                } else if (logLevel === ConsoleLogLevel.Warn) {
                    this.consoleWarnCount++
                } else if (logLevel === ConsoleLogLevel.Error) {
                    this.consoleErrorCount++
                }
            }
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
