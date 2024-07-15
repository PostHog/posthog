import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'

import { ClickHouseTimestamp, RRWebEvent, TimestampFormat } from '../../../types'
import { status } from '../../../utils/status'
import { castTimestampOrNow } from '../../../utils/utils'
import { activeMilliseconds } from './snapshot-segmenter'

function sanitizeForUTF8(input: string): string {
    // the JS console truncates some logs...
    // when it does that it doesn't check if the output is valid UTF-8
    // and so it can truncate halfway through a UTF-16 pair 🤷
    // the simplest way to fix this is to convert to a buffer and back
    // annoyingly Node 20 has `toWellFormed` which might have been useful
    const buffer = Buffer.from(input)
    return buffer.toString()
}

function safeString(payload: (string | null)[]) {
    // the individual strings are sometimes wrapped in quotes... we want to strip those
    return payload
        .filter((item: unknown): item is string => !!item && typeof item === 'string')
        .map((item) => sanitizeForUTF8(item.substring(0, 2999)))
        .join(' ')
}

export interface SummarizedSessionRecordingEvent {
    uuid: string
    first_timestamp: string
    last_timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    first_url: string | null
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    active_milliseconds: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
    event_count: number
    message_count: number
    snapshot_source: string | null
}

// this is of course way more complicated than you'd expect
// https://console.spec.whatwg.org/#loglevel-severity
const browserLogLevels = [
    'log',
    'trace',
    'dir',
    'dirxml',
    'group',
    'groupCollapsed',
    'debug',
    'timeLog',
    'info',
    'count',
    'timeEnd',
    'warn',
    'countReset',
    'error',
    'assert',
    'warn',
    'countReset',
    'error',
    'assert',
] as const
type BrowserLogLevel = (typeof browserLogLevels)[number]
// we don't want that many log levels
const logLevels = ['info', 'warn', 'error'] as const
export type LogLevel = (typeof logLevels)[number]

const levelMapping: Record<BrowserLogLevel, LogLevel> = {
    info: 'info',
    count: 'info',
    timeEnd: 'info',
    warn: 'warn',
    countReset: 'warn',
    error: 'error',
    assert: 'error',
    // really these should be 'log' but we don't want users to have to think about this
    log: 'info',
    trace: 'info',
    dir: 'info',
    dirxml: 'info',
    group: 'info',
    groupCollapsed: 'info',
    debug: 'info',
    timeLog: 'info',
}

// level is effectively user provided input, so we don't want to fire it into kafka to head to CH
// without ensuring it only has known/expected values
function safeLevel(level: unknown): LogLevel {
    const needle = typeof level === 'string' ? level : 'info'
    return levelMapping[needle as BrowserLogLevel] || 'info'
}

export type ConsoleLogEntry = {
    team_id: number
    message: string
    level: LogLevel
    log_source: 'session_replay'
    // the session_id
    log_source_id: string
    // The ClickHouse log_entries table collapses input based on its order by key
    // team_id, log_source, log_source_id, instance_id, timestamp
    // since we don't have a natural instance id, we don't send one.
    // This means that if we can log two messages for one session with the same timestamp
    // we might lose one of them
    // in practice console log timestamps are pretty precise: 2023-10-04 07:53:29.586
    // so, this is unlikely enough that we can avoid filling the DB with UUIDs only to avoid losing
    // a very, very small proportion of console logs.
    instance_id: string | null
    timestamp: ClickHouseTimestamp
}

/**
 * copied from @rrweb-types
 */
export enum RRWebEventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
    Plugin = 6,
}

enum RRWebEventSource {
    Mutation = 0,
    MouseMove = 1,
    MouseInteraction = 2,
    Scroll = 3,
    ViewportResize = 4,
    Input = 5,
    TouchMove = 6,
    MediaInteraction = 7,
    StyleSheetRule = 8,
    CanvasMutation = 9,
    Font = 10,
    Log = 11,
    Drag = 12,
    StyleDeclaration = 13,
    Selection = 14,
    AdoptedStyleSheet = 15,
}

enum MouseInteractions {
    MouseUp = 0,
    MouseDown = 1,
    Click = 2,
    ContextMenu = 3,
    DblClick = 4,
    Focus = 5,
    Blur = 6,
    TouchStart = 7,
    TouchMove_Departed = 8,
    TouchEnd = 9,
    TouchCancel = 10,
}

/**
 * end copied section from @rrweb-types
 */

export const gatherConsoleLogEvents = (
    team_id: number,
    session_id: string,
    events: RRWebEvent[]
): ConsoleLogEntry[] => {
    const consoleLogEntries: ConsoleLogEntry[] = []

    events.forEach((event) => {
        // it should be unnecessary to check for truthiness of event here,
        // but we've seen null in production so 🤷
        if (!!event && event.type === RRWebEventType.Plugin && event.data?.plugin === 'rrweb/console@1') {
            try {
                const level = safeLevel(event.data.payload?.level)
                const message = safeString(event.data.payload?.payload)
                consoleLogEntries.push({
                    team_id,
                    message: message,
                    level: level,
                    log_source: 'session_replay',
                    log_source_id: session_id,
                    instance_id: null,
                    timestamp: castTimestampOrNow(DateTime.fromMillis(event.timestamp), TimestampFormat.ClickHouse),
                })
            } catch (e) {
                // if we can't process a console log, we don't want to lose the whole shebang
                captureException(e, { extra: { messagePayload: event.data.payload?.payload }, tags: { session_id } })
            }
        }
    })

    return consoleLogEntries
}
export const getTimestampsFrom = (events: RRWebEvent[]): ClickHouseTimestamp[] =>
    events
        // from millis expects a number and handles unexpected input gracefully so we have to do some filtering
        // since we're accepting input over the API and have seen very unexpected values in the past
        // we want to be very careful here before converting to a DateTime
        // TODO we don't really want to support timestamps of 1,
        //  but we don't currently filter out based on date of RRWebEvents being too far in the past
        .filter((e) => (e?.timestamp || -1) > 0)
        .map((e) => DateTime.fromMillis(e.timestamp))
        .filter((e) => e.isValid)
        .map((e) => castTimestampOrNow(e, TimestampFormat.ClickHouse))
        .sort()

function isClick(event: RRWebEvent) {
    const couldBeClick =
        event.type === RRWebEventType.IncrementalSnapshot && event.data?.source === RRWebEventSource.MouseInteraction
    const isClick =
        couldBeClick &&
        [
            MouseInteractions.Click,
            MouseInteractions.DblClick,
            MouseInteractions.TouchEnd,
            MouseInteractions.ContextMenu, // right click
        ].includes(event.data?.type || -1)
    return couldBeClick && isClick
}

function isAnyMouseActivity(event: RRWebEvent) {
    return (
        event.type === RRWebEventType.IncrementalSnapshot &&
        [RRWebEventSource.MouseInteraction, RRWebEventSource.MouseMove, RRWebEventSource.TouchMove].includes(
            event.data?.source || -1
        )
    )
}

/**
 * meta event has type = 4 and event.data.href
 * and custom events have type = 5 and _might_ have event.data.payload.href
 *
 * we don't really care what type of event they are just whether they have a href
 */
function hrefFrom(event: RRWebEvent): string | undefined {
    const metaHref = event.data?.href?.trim()
    const customHref = event.data?.payload?.href?.trim()
    return metaHref || customHref || undefined
}

export const createSessionReplayEvent = (
    uuid: string,
    team_id: number,
    distinct_id: string,
    session_id: string,
    events: RRWebEvent[],
    snapshot_source: string | null
): { event: SummarizedSessionRecordingEvent; warnings: string[] } => {
    const timestamps = getTimestampsFrom(events)

    // but every event where chunk index = 0 must have an eventsSummary
    if (events.length === 0 || timestamps.length === 0) {
        status.warn('🙈', 'ignoring an empty session recording event', {
            session_id,
            events,
        })
        // it is safe to throw here as it caught a level up so that we can see this happening in Sentry
        throw new Error('ignoring an empty session recording event')
    }

    const warnings: string[] = []

    let clickCount = 0
    let keypressCount = 0
    let mouseActivity = 0
    let consoleLogCount = 0
    let consoleWarnCount = 0
    let consoleErrorCount = 0
    let url: string | null = null
    events.forEach((event) => {
        if (event.type === RRWebEventType.IncrementalSnapshot) {
            if (isClick(event)) {
                clickCount += 1
            }
            if (isAnyMouseActivity(event)) {
                mouseActivity += 1
            }
            if (event.data?.source === RRWebEventSource.Input) {
                keypressCount += 1
            }
        }

        const eventUrl: string | undefined = hrefFrom(event)
        if (url === null && eventUrl) {
            url = eventUrl
        }

        if (event.type === RRWebEventType.Plugin && event.data?.plugin === 'rrweb/console@1') {
            const level = safeLevel(event.data.payload?.level)
            if (level === 'info') {
                consoleLogCount += 1
            } else if (level === 'warn') {
                consoleWarnCount += 1
            } else if (level === 'error') {
                consoleErrorCount += 1
            }
        }

        if (event.type === RRWebEventType.Custom && event.data?.tag === 'Message too large') {
            warnings.push('replay_message_too_large')
        }
    })

    const activeTime = activeMilliseconds(events)

    // NB forces types to be correct e.g. by truncating or rounding
    // to ensure we don't send floats when we should send an integer
    const data: SummarizedSessionRecordingEvent = {
        uuid,
        team_id: team_id,
        distinct_id: String(distinct_id),
        session_id: session_id,
        first_timestamp: timestamps[0],
        last_timestamp: timestamps[timestamps.length - 1],
        click_count: Math.trunc(clickCount),
        keypress_count: Math.trunc(keypressCount),
        mouse_activity_count: Math.trunc(mouseActivity),
        first_url: url,
        active_milliseconds: Math.round(activeTime),
        console_log_count: Math.trunc(consoleLogCount),
        console_warn_count: Math.trunc(consoleWarnCount),
        console_error_count: Math.trunc(consoleErrorCount),
        size: Math.trunc(Buffer.byteLength(JSON.stringify(events), 'utf8')),
        event_count: Math.trunc(events.length),
        message_count: 1,
        snapshot_source: snapshot_source || 'web',
    }

    return { event: data, warnings }
}
