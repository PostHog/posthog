import { actions, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils'
import { chainToElements } from 'lib/utils/elements-chain'
import { TimeTree } from 'lib/utils/time-tree'

import { HogQLQueryString, hogql } from '~/queries/utils'
import { RecordingEventType } from '~/types'

import type { sessionEventsDataLogicType } from './sessionEventsDataLogicType'
import { SessionRecordingMetaLogicProps, sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'
import { ViewportResolution } from './snapshot-processing/patch-meta-event'

const TWENTY_FOUR_HOURS_IN_MS = 24 * 60 * 60 * 1000 // +- before and after start and end of a recording to query for session linked events.
const FIVE_MINUTES_IN_MS = 5 * 60 * 1000 // +- before and after start and end of a recording to query for events related by person.

export const sessionEventsDataLogic = kea<sessionEventsDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionEventsDataLogic', key]),
    props({} as SessionRecordingMetaLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect((props: SessionRecordingMetaLogicProps) => {
        const metaLogic = sessionRecordingMetaLogic(props)
        return {
            values: [metaLogic, ['sessionPlayerMetaData']],
            actions: [metaLogic, ['loadRecordingMetaSuccess']],
        }
    }),
    actions({
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType | RecordingEventType[]) => ({ event }),
    }),
    reducers(() => ({})),
    loaders(({ values, props }) => ({
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    const meta = values.sessionPlayerMetaData
                    if (!meta) {
                        return null
                    }

                    const start = meta.start_time ? dayjs(meta.start_time) : null
                    const end = meta.end_time ? dayjs(meta.end_time) : null
                    const person = meta.person

                    if (!person || !start || !end) {
                        return null
                    }

                    const sessionEventsQuery = hogql`
SELECT uuid, event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type, properties.$viewport_width, properties.$viewport_height, properties.$screen_name, distinct_id
FROM events
WHERE timestamp > ${start.subtract(TWENTY_FOUR_HOURS_IN_MS, 'ms')}
AND timestamp < ${end.add(TWENTY_FOUR_HOURS_IN_MS, 'ms')}
AND $session_id = ${props.sessionRecordingId}
ORDER BY timestamp ASC
LIMIT 1000000`

                    let relatedEventsQuery = hogql`
SELECT uuid, event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type, distinct_id
FROM events
WHERE timestamp > ${start.subtract(FIVE_MINUTES_IN_MS, 'ms')}
AND timestamp < ${end.add(FIVE_MINUTES_IN_MS, 'ms')}
AND (empty ($session_id) OR isNull($session_id))
AND properties.$lib != 'web'`

                    if (person?.uuid) {
                        relatedEventsQuery = (relatedEventsQuery +
                            hogql`\nAND person_id = ${person.uuid}`) as HogQLQueryString
                    }
                    if (!person?.uuid && values.sessionPlayerMetaData?.distinct_id) {
                        relatedEventsQuery = (relatedEventsQuery +
                            hogql`\nAND distinct_id = ${values.sessionPlayerMetaData.distinct_id}`) as HogQLQueryString
                    }

                    relatedEventsQuery = (relatedEventsQuery +
                        hogql`\nORDER BY timestamp ASC\nLIMIT 1000000`) as HogQLQueryString

                    const [sessionEvents, relatedEvents]: any[] = await Promise.all([
                        // make one query for all events that are part of the session
                        api.queryHogQL(sessionEventsQuery),
                        // make a second for all events from that person,
                        // not marked as part of the session
                        // but in the same time range
                        // these are probably e.g. backend events for the session
                        // but with no session id
                        // since posthog-js must always add session id we can also
                        // take advantage of lib being materialized and further filter
                        api.queryHogQL(relatedEventsQuery),
                    ])

                    return [...sessionEvents.results, ...relatedEvents.results].map(
                        (event: any): RecordingEventType => {
                            const currentUrl = event[5]
                            // We use the pathname to simplify the UI - we build it here instead of fetching it to keep data usage small
                            let pathname: string | undefined
                            try {
                                pathname = event[5] ? new URL(event[5]).pathname : undefined
                            } catch {
                                pathname = undefined
                            }

                            const viewportWidth = event.length > 7 ? event[7] : undefined
                            const viewportHeight = event.length > 8 ? event[8] : undefined

                            return {
                                id: event[0],
                                event: event[1],
                                timestamp: event[2],
                                elements: chainToElements(event[3]),
                                properties: {
                                    $window_id: event[4],
                                    $current_url: currentUrl,
                                    $event_type: event[6],
                                    $pathname: pathname,
                                    $viewport_width: viewportWidth,
                                    $viewport_height: viewportHeight,
                                    $screen_name: event.length > 9 ? event[9] : undefined,
                                },
                                playerTime: +dayjs(event[2]) - +start,
                                fullyLoaded: false,
                                distinct_id: event[event.length - 1] || values.sessionPlayerMetaData?.distinct_id,
                            }
                        }
                    )
                },

                loadFullEventData: async ({ event }) => {
                    // box so we're always dealing with a list
                    const events = Array.isArray(event) ? event : [event]

                    let existingEvents = values.sessionEventsData?.filter((x) => events.some((e) => e.id === x.id))

                    const allEventsAreFullyLoaded =
                        existingEvents?.every((e) => e.fullyLoaded) && existingEvents.length === events.length
                    if (!existingEvents || allEventsAreFullyLoaded) {
                        return values.sessionEventsData
                    }

                    existingEvents = existingEvents.filter((e) => !e.fullyLoaded)
                    const timestamps = existingEvents.map((ee) => dayjs(ee.timestamp).utc().valueOf())
                    const eventNames = Array.from(new Set(existingEvents.map((ee) => ee.event)))
                    const eventIds = existingEvents.map((ee) => ee.id)
                    const earliestTimestamp = timestamps.reduce((a, b) => Math.min(a, b))
                    const latestTimestamp = timestamps.reduce((a, b) => Math.max(a, b))

                    try {
                        const query = hogql`
                            SELECT properties, uuid
                            FROM events
                            -- the timestamp range here is only to avoid querying too much of the events table
                            -- we don't really care about the absolute value,
                            -- but we do care about whether timezones have an odd impact
                            -- so, we extend the range by a day on each side so that timezones don't cause issues
                            WHERE timestamp > ${dayjs(earliestTimestamp).subtract(1, 'day')}
                            AND timestamp < ${dayjs(latestTimestamp).add(1, 'day')}
                            AND event in ${eventNames}
                            AND uuid in ${eventIds}`

                        const response = await api.queryHogQL(query)
                        if (response.error) {
                            throw new Error(response.error)
                        }

                        for (const event of existingEvents) {
                            const result = response.results.find((x: any) => {
                                return x[1] === event.id
                            })

                            if (result) {
                                event.properties = JSON.parse(result[0])
                                event.fullyLoaded = true
                            }
                        }
                    } catch (e) {
                        // NOTE: This is not ideal but should happen so rarely that it is tolerable.
                        existingEvents.forEach((e) => (e.fullyLoaded = true))
                        posthog.captureException(e, { feature: 'session-recording-load-full-event-data' })
                    }

                    // here we map the events list because we want the result to be a new instance to trigger downstream recalculation
                    return !values.sessionEventsData
                        ? values.sessionEventsData
                        : values.sessionEventsData.map((x) => {
                              const event = existingEvents?.find((ee) => ee.id === x.id)
                              return event
                                  ? ({
                                        ...x,
                                        properties: event.properties,
                                        fullyLoaded: event.fullyLoaded,
                                    } as RecordingEventType)
                                  : x
                          })
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadRecordingMetaSuccess: () => {
            actions.loadEvents()
        },
    })),
    selectors(() => ({
        webVitalsEvents: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): RecordingEventType[] =>
                (sessionEventsData || []).filter((e) => e.event === '$web_vitals'),
        ],
        AIEvents: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): RecordingEventType[] =>
                // see if event start with $ai_
                (sessionEventsData || []).filter((e) => e.event.startsWith('$ai_')),
        ],
        exceptionEvents: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): RecordingEventType[] =>
                (sessionEventsData || []).filter((e) => e.event === '$exception'),
        ],
        preloadableEvents: [
            (s) => [s.webVitalsEvents, s.AIEvents, s.exceptionEvents],
            (webVitalsEvents, AIEvents, exceptionEvents): RecordingEventType[] => [
                ...webVitalsEvents,
                ...AIEvents,
                ...exceptionEvents,
            ],
            { resultEqualityCheck: objectsEqual },
        ],
        eventViewportsItems: [
            (s) => [s.sessionEventsData],
            (
                sessionEventsData
            ): TimeTree<{
                timestamp: Dayjs
                payload: ViewportResolution
            }> => {
                const viewportEvents = new TimeTree<{
                    timestamp: Dayjs
                    payload: ViewportResolution
                }>()
                viewportEvents.add(
                    (sessionEventsData || [])
                        .filter((e) => e.properties.$viewport_width && e.properties.$viewport_height)
                        .map((e) => ({
                            timestamp: dayjs(e.timestamp),
                            payload: {
                                width: e.properties.$viewport_width,
                                height: e.properties.$viewport_height,
                                href: e.properties.$current_url,
                            },
                        }))
                )
                return viewportEvents
            },
            { resultEqualityCheck: objectsEqual },
        ],
        viewportForTimestamp: [
            (s) => [s.eventViewportsItems],
            (eventViewportsItems) => {
                return (timestamp: number) => {
                    const closestItem =
                        eventViewportsItems.next(dayjs(timestamp)) || eventViewportsItems.previous(dayjs(timestamp))
                    if (!closestItem) {
                        return undefined
                    }
                    return closestItem.payload as ViewportResolution
                }
            },
        ],
    })),
    subscriptions(({ actions }) => ({
        preloadableEvents: (pe: null | RecordingEventType[]) => {
            if (pe?.length) {
                actions.loadFullEventData(pe)
            }
        },
    })),
    beforeUnmount(({ cache }) => {
        cache.windowIdForTimestamp = undefined
        cache.viewportForTimestamp = undefined
        cache.processingCache = undefined
    }),
])
