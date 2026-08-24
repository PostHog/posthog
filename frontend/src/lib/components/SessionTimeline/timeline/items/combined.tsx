/**
 * Combined event loader — fetches exceptions, pageviews, screen views, and custom
 * events in a single EventsQuery instead of separate ones. Register the same
 * instance for every event category so the collector deduplicates it.
 */
import api from 'lib/api'
import { ErrorTrackingException, ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { Dayjs, dayjs } from 'lib/dayjs'

import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'

import { ItemCategory, ItemLoader, TimelineItem } from '..'
import { escapeHogQLString, parseIfJSONString } from './parsing'

const WINDOW_HOURS = 1

const SELECT = [
    'uuid',
    'event',
    'timestamp',
    'properties.$lib',
    'properties.$current_url',
    'properties.$screen_name',
    'properties.$exception_list',
    'properties.$exception_fingerprint',
    'properties.$exception_issue_id',
]

type RawCombinedEventRow = [
    uuid: unknown,
    eventName: unknown,
    timestamp: unknown,
    lib: unknown,
    currentUrl: unknown,
    screenName: unknown,
    rawExceptionList: unknown,
    exceptionFingerprint: unknown,
    exceptionIssueId: unknown,
]

interface ParsedCombinedEventRow {
    uuid: string
    eventName: string
    timestamp: string
    lib?: string
    currentUrl?: string
    screenName?: string
    rawExceptionList: unknown
    exceptionFingerprint?: string
    exceptionIssueId?: string
}

interface CombinedEventQueryResponse {
    results?: unknown[]
}

function buildWhere(sessionId: string): string[] {
    return [
        `equals($session_id, '${escapeHogQLString(sessionId)}')`,
        "or(equals(event, '$exception'), equals(event, '$pageview'), equals(event, '$screen'), notEquals(left(event, 1), '$'))",
    ]
}

export class CombinedEventLoader implements ItemLoader<TimelineItem> {
    constructor(
        private readonly sessionId: string,
        private readonly centerTimestamp: Dayjs
    ) {}

    async loadBefore(cursor: Dayjs, limit: number): Promise<{ items: TimelineItem[]; hasMoreBefore: boolean }> {
        const query: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: SELECT,
            where: buildWhere(this.sessionId),
            after: cursor.subtract(WINDOW_HOURS, 'hours').toISOString(),
            before: cursor.toISOString(),
            orderBy: ['timestamp DESC'],
            limit,
        }
        const response = (await api.query(query)) as CombinedEventQueryResponse
        const rawResults = Array.isArray(response.results) ? response.results : []
        const items = parseItemsFromResults(rawResults)
        return {
            items,
            hasMoreBefore: rawResults.length === limit,
        }
    }

    async loadAfter(cursor: Dayjs, limit: number): Promise<{ items: TimelineItem[]; hasMoreAfter: boolean }> {
        const query: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: SELECT,
            where: buildWhere(this.sessionId),
            after: cursor.toISOString(),
            before: this.centerTimestamp.add(WINDOW_HOURS, 'hours').toISOString(),
            orderBy: ['timestamp ASC'],
            limit,
        }
        const response = (await api.query(query)) as CombinedEventQueryResponse
        const rawResults = Array.isArray(response.results) ? response.results : []
        const items = parseItemsFromResults(rawResults)
        return {
            items,
            hasMoreAfter: rawResults.length === limit,
        }
    }
}

function parseItemsFromResults(results: unknown[] | undefined): TimelineItem[] {
    if (!Array.isArray(results)) {
        return []
    }

    return results
        .map(parseCombinedEventRow)
        .filter((row): row is ParsedCombinedEventRow => Boolean(row))
        .map(buildItem)
}

function parseCombinedEventRow(row: unknown): ParsedCombinedEventRow | null {
    if (!Array.isArray(row) || row.length < 9) {
        return null
    }

    const [
        uuid,
        eventName,
        timestamp,
        lib,
        currentUrl,
        screenName,
        rawExceptionList,
        exceptionFingerprint,
        exceptionIssueId,
    ] = row as RawCombinedEventRow

    if (typeof uuid !== 'string' || typeof eventName !== 'string') {
        return null
    }

    if (typeof timestamp !== 'string' && typeof timestamp !== 'number' && !(timestamp instanceof Date)) {
        return null
    }

    const timestampValue = dayjs.utc(timestamp)
    if (!timestampValue.isValid()) {
        return null
    }

    return {
        uuid,
        eventName,
        timestamp: timestampValue.toISOString(),
        lib: typeof lib === 'string' ? lib : undefined,
        currentUrl: typeof currentUrl === 'string' ? currentUrl : undefined,
        screenName: typeof screenName === 'string' ? screenName : undefined,
        rawExceptionList,
        exceptionFingerprint: typeof exceptionFingerprint === 'string' ? exceptionFingerprint : undefined,
        exceptionIssueId: typeof exceptionIssueId === 'string' ? exceptionIssueId : undefined,
    }
}

function buildItem(evt: ParsedCombinedEventRow): TimelineItem {
    const ts = dayjs.utc(evt.timestamp)
    const runtime: ErrorTrackingRuntime = getRuntimeFromLib(evt.lib)

    if (evt.eventName === '$exception') {
        const exceptionList: ErrorTrackingException[] | undefined = parseIfJSONString(evt.rawExceptionList)
        return {
            id: evt.uuid,
            category: ItemCategory.ERROR_TRACKING,
            timestamp: ts,
            payload: {
                runtime,
                type: exceptionList?.[0]?.type,
                message: exceptionList?.[0]?.value,
                fingerprint: evt.exceptionFingerprint,
                issue_id: evt.exceptionIssueId,
            },
        }
    }

    if (evt.eventName === '$pageview') {
        return {
            id: evt.uuid,
            category: ItemCategory.PAGE_VIEWS,
            timestamp: ts,
            payload: { runtime, url: evt.currentUrl ?? '' },
        }
    }

    if (evt.eventName === '$screen') {
        return {
            id: evt.uuid,
            category: ItemCategory.SCREEN_VIEWS,
            timestamp: ts,
            payload: { runtime, name: evt.screenName ?? '' },
        }
    }

    // Custom event (anything not starting with $)
    return {
        id: evt.uuid,
        category: ItemCategory.CUSTOM_EVENTS,
        timestamp: ts,
        payload: { runtime, name: evt.eventName },
    }
}
