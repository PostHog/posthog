import { useEffect, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SessionEventDetails } from 'scenes/sessions/components/SessionEventDetails'

import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingEventType } from '~/types'

import { RendererProps, TimelineItem } from '..'

const eventDetailsCache = new Map<string, RecordingEventType | null>()
const eventDetailsInFlight = new Map<string, Promise<RecordingEventType | null>>()
const EVENT_DETAILS_CACHE_MAX_ENTRIES = 200

type EventDetailsRow = [uuid: unknown, eventName: unknown, timestamp: unknown, properties: unknown]

interface EventDetailsQueryResponse {
    results?: unknown[]
}

function parseProperties(value: unknown): Record<string, any> {
    if (!value) {
        return {}
    }
    if (typeof value === 'string') {
        try {
            return JSON.parse(value)
        } catch {
            return {}
        }
    }
    if (typeof value === 'object') {
        return value as Record<string, any>
    }
    return {}
}

function buildEventFromRow(row: unknown): RecordingEventType | null {
    if (!Array.isArray(row) || row.length < 4) {
        return null
    }

    const [uuid, eventName, timestamp, properties] = row as EventDetailsRow
    const parsedProperties = parseProperties(properties)

    return {
        id: String(uuid),
        uuid: String(uuid),
        event: String(eventName),
        timestamp: String(timestamp),
        properties: parsedProperties,
        fullyLoaded: true,
    } as RecordingEventType
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

function escapeHogQLString(value: string): string {
    return value.replaceAll('\\', '\\\\').replaceAll("'", "\\'")
}

async function fetchEventDetails(itemId: string): Promise<RecordingEventType | null> {
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
            where: [`equals(uuid, '${escapeHogQLString(itemId)}')`],
            limit: 1,
        })
        .then((response: EventDetailsQueryResponse) => buildEventFromRow(response.results?.[0]))
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

export const LazyEventDetailsRenderer: React.FC<RendererProps<TimelineItem>> = ({ item }): JSX.Element => {
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

        fetchEventDetails(item.id)
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
    }, [item.id])

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
