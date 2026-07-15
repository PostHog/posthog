import { DateTime } from 'luxon'

import { sanitizeForUTF8 } from '~/common/utils/strings'
import { castTimestampOrNow } from '~/common/utils/utils'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { ConsoleLogLevel, RRWebEventType } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { ExtractedConsoleLogs } from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-recorder'
import { MessageWithTeam, TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { TimestampFormat } from '~/types'

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

export interface ExtractConsoleLogsStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

export interface ExtractConsoleLogsStepOutput {
    logs: ExtractedConsoleLogs
}

/**
 * Extracts the per-message console log data from a parsed message. Pure business logic — the
 * record step aggregates the result into the session batch without looking at the raw events
 * again.
 */
export function createExtractConsoleLogsStep<T extends ExtractConsoleLogsStepInput>(): ProcessingStep<
    T,
    T & ExtractConsoleLogsStepOutput
> {
    return function extractConsoleLogsStep(input) {
        const { team, parsedMessage } = input
        return Promise.resolve(
            ok({
                ...input,
                logs: extractConsoleLogs({ team, message: parsedMessage }),
            })
        )
    }
}
