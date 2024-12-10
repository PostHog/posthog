import { captureException } from '@sentry/react'
import { actions, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { chainToElements } from 'lib/utils/elements-chain'
import { SessionRecordingDataLogicProps } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { PersonType, RecordingEventType, SessionPlayerData } from '~/types'

import type { sessionRecordingEventDataLogicType } from './sessionRecordingEventDataLogicType'

const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

function makeEventsQuery(
    person: PersonType | null,
    distinctIds: string[] | null,
    start: Dayjs,
    end: Dayjs,
    sessionId: string
): Promise<unknown> {
    if (person === null && sessionId === '') {
        console.error('replay event queries must always have a session id or a person')
        return Promise.resolve({
            results: [],
        })
    }
    return api.query({
        kind: NodeKind.HogQLQuery,
        query: `
        select  uuid,
            event,
            timestamp,
            elements_chain,
            properties.$window_id,
            properties.$current_url,
            properties.$event_type,
            from events
        where timestamp > ${start.subtract(BUFFER_MS, 'ms').format()}
        and timestamp < ${end.add(BUFFER_MS, 'ms').format()}
        and ${person ? `person_id = ${person.id}` : '1=1'}
        and ${distinctIds?.length ? `distinct_id in ${distinctIds}` : '1=1'}
        and $session_id = ${sessionId}
        -- if we're not querying by session id then we can take advantage of knowing that posthog-js always sets it
        -- and filter by $lib which is always materialized so should be pretty fast
        and ${sessionId === '' ? "properties.$lib != 'web'" : '1=1'}
        order by timestamp asc
        limit 1000000`,
    })
}

export const sessionRecordingEventDataLogic = kea<sessionRecordingEventDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingEventDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    actions({
        loadEvents: (sessionPlayerData: SessionPlayerData) => ({ ...sessionPlayerData }),
        loadFullEventData: (event: RecordingEventType | RecordingEventType[]) => ({ event }),
    }),
    loaders(({ values, props }) => ({
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async ({ start, end, person }) => {
                    if (!person || !start || !end) {
                        return null
                    }

                    const [sessionEvents, relatedEvents]: any[] = await Promise.all([
                        // make one query for all events that are part of the session
                        makeEventsQuery(null, null, start, end, props.sessionRecordingId),
                        // make a second for all events from that person,
                        // not marked as part of the session
                        // but in the same time range
                        // these are probably e.g. backend events for the session
                        // but with no session id
                        // since posthog-js must always add session id we can also
                        // take advantage of lib being materialized and further filter
                        makeEventsQuery(null, person?.distinct_ids || null, start, end, props.sessionRecordingId),
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
                                },
                                playerTime: +dayjs(event[2]) - +start,
                                fullyLoaded: false,
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
                        const query: HogQLQuery = {
                            kind: NodeKind.HogQLQuery,
                            query: hogql`SELECT properties, uuid
                                         FROM events
                                         WHERE timestamp > ${(earliestTimestamp - 1000) / 1000}
                                           AND timestamp < ${(latestTimestamp + 1000) / 1000}
                                           AND event in ${eventNames}
                                           AND uuid in ${eventIds}`,
                        }
                        const response = await api.query(query)
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
                        captureException(e, {
                            tags: { feature: 'session-recording-load-full-event-data' },
                        })
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
    selectors({
        webVitalsEvents: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): RecordingEventType[] =>
                (sessionEventsData || []).filter((e) => e.event === '$web_vitals'),
        ],
    }),
    subscriptions(({ actions, values }) => ({
        webVitalsEvents: (value: RecordingEventType[]) => {
            // we preload all web vitals data, so it can be used before user interaction
            if (!values.sessionEventsDataLoading) {
                actions.loadFullEventData(value)
            }
        },
    })),
])
