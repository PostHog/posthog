import { useEffect, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SessionEventDetails } from 'scenes/sessions/components/SessionEventDetails'

import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingEventType } from '~/types'

import { ItemCategory, RendererProps, TimelineItem } from '..'
import { escapeHogQLString, parseRecordIfJSONString } from './parsing'

const eventDetailsCache = new Map<string, RecordingEventType | null>()
const eventDetailsInFlight = new Map<string, Promise<RecordingEventType | null>>()
const EVENT_DETAILS_CACHE_MAX_ENTRIES = 200
const EVENT_DETAILS_QUERY_WINDOW_MS = 1000
const EVENT_DETAILS_QUERY_LIMIT = 100

type EventDetailsRow = [uuid: unknown, eventName: unknown, timestamp: unknown, properties: unknown]

interface EventDetailsQueryResponse {
    results?: unknown[]
}

function getCategoryWhereClause(category: TimelineItem['category']): string | null {
    switch (category) {
        case ItemCategory.ERROR_TRACKING:
            return "equals(event, '$exception')"
        case ItemCategory.PAGE_VIEWS:
            return "equals(event, '$pageview')"
        case ItemCategory.CUSTOM_EVENTS:
            return "notEquals(left(event, 1), '$')"
        default:
            return null
    }
}

function shouldFilterBySessionId(item: TimelineItem, sessionId?: string): boolean {
    if (!sessionId) {
        return false
    }

    // In no-session fallback timelines, collector.sessionId is the exception UUID.
    // Avoid treating that synthetic value as a real session filter.
    return sessionId !== item.id
}

function buildEventDetailsWhere(item: TimelineItem, sessionId?: string): string[] {
    const where: string[] = [`equals(uuid, '${escapeHogQLString(item.id)}')`]

    if (sessionId && shouldFilterBySessionId(item, sessionId)) {
        where.push(`equals($session_id, '${escapeHogQLString(sessionId)}')`)
    }

    const categoryWhereClause = getCategoryWhereClause(item.category)
    if (categoryWhereClause) {
        where.push(categoryWhereClause)
    }

    return where
}

function buildEventFromRow(row: unknown): RecordingEventType | null {
    if (!Array.isArray(row) || row.length < 4) {
        return null
    }

    const [uuid, eventName, timestamp, properties] = row as EventDetailsRow
    const parsedProperties = parseRecordIfJSONString(properties)

    const event: RecordingEventType & { uuid: string } = {
        id: String(uuid),
        uuid: String(uuid),
        event: String(eventName),
        timestamp: String(timestamp),
        properties: parsedProperties,
        elements: [],
        playerTime: null,
        fullyLoaded: true,
    }

    return event
}

function parseEventDetailsQueryResponse(response: unknown): EventDetailsQueryResponse {
    if (!response || typeof response !== 'object' || Array.isArray(response)) {
        return {}
    }

    const results = (response as { results?: unknown }).results
    return {
        results: Array.isArray(results) ? results : [],
    }
}

function setCachedEvent(itemId: string, event: RecordingEventType | null): void {
    if (eventDetailsCache.has(itemId)) {
        eventDetailsCache.delete(itemId)
    }

    eventDetailsCache.set(itemId, event)

    if (eventDetailsCache.size > EVENT_DETAILS_CACHE_MAX_ENTRIES) {
        const oldestKey = eventDetailsCache.keys().next().value
        if (oldestKey !== undefined) {
            eventDetailsCache.delete(oldestKey)
        }
    }
}

async function fetchEventDetails(item: TimelineItem, sessionId?: string): Promise<RecordingEventType | null> {
    const itemId = item.id

    if (eventDetailsCache.has(itemId)) {
        return eventDetailsCache.get(itemId) ?? null
    }

    if (eventDetailsInFlight.has(itemId)) {
        return (await eventDetailsInFlight.get(itemId)) ?? null
    }

    const request = api
        .query({
            kind: NodeKind.EventsQuery,
            select: ['uuid', 'event', 'timestamp', 'properties'],
            where: buildEventDetailsWhere(item, sessionId),
            after: item.timestamp.subtract(EVENT_DETAILS_QUERY_WINDOW_MS, 'millisecond').toISOString(),
            before: item.timestamp.add(EVENT_DETAILS_QUERY_WINDOW_MS, 'millisecond').toISOString(),
            orderBy: ['timestamp ASC'],
            limit: EVENT_DETAILS_QUERY_LIMIT,
        })
        .then((response) => {
            const parsedResponse = parseEventDetailsQueryResponse(response)
            const results = parsedResponse.results ?? []
            const exactUuidMatch = results.find((row) => Array.isArray(row) && String(row[0]) === itemId)
            return buildEventFromRow(exactUuidMatch ?? results[0])
        })
        .catch(() => null)
        .then((event) => {
            setCachedEvent(itemId, event)
            return event
        })
        .finally(() => {
            eventDetailsInFlight.delete(itemId)
        })

    eventDetailsInFlight.set(itemId, request)
    return await request
}

export const LazyEventDetailsRenderer: React.FC<RendererProps<TimelineItem>> = ({ item, sessionId }): JSX.Element => {
    const [event, setEvent] = useState<RecordingEventType | null>(() => eventDetailsCache.get(item.id) ?? null)
    const [loading, setLoading] = useState<boolean>(() => !eventDetailsCache.has(item.id))

    useEffect(() => {
        let mounted = true

        if (eventDetailsCache.has(item.id)) {
            setEvent(eventDetailsCache.get(item.id) ?? null)
            setLoading(false)
            return
        }

        setEvent(null)
        setLoading(true)

        fetchEventDetails(item, sessionId)
            .then((result) => {
                if (!mounted) {
                    return
                }

                setEvent(result)
            })
            .finally(() => {
                if (mounted) {
                    setLoading(false)
                }
            })

        return () => {
            mounted = false
        }
    }, [item.id, item.category, item.timestamp, sessionId])

    if (loading) {
        return (
            <div className="p-2 text-xs text-secondary flex items-center gap-2">
                <Spinner textColored />
                <span>Loading event details...</span>
            </div>
        )
    }

    if (!event) {
        return <div className="p-2 text-xs text-secondary">Event details unavailable</div>
    }

    return <SessionEventDetails event={event} errorDisplayIdSuffix="session-timeline-expanded" />
}
