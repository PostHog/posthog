import { customEvent, EventType, eventWithTime } from '@posthog/rrweb-types'
import { actions, beforeUnmount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { chainToElements } from 'lib/utils/elements-chain'
import posthog from 'posthog-js'
import {
    InspectorListItemAnnotationComment,
    RecordingComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import {
    parseEncodedSnapshots,
    processAllSnapshots,
    processAllSnapshotsRaw,
} from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { teamLogic } from 'scenes/teamLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { hogql, HogQLQueryString } from '~/queries/utils'
import {
    AnnotationScope,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionRecordingId,
    SessionRecordingSnapshotParams,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
    SessionRecordingType,
    SessionRecordingUsageType,
    SnapshotSourceType,
} from '~/types'

import { ExportedSessionRecordingFileV2, ExportedSessionType } from '../file-playback/types'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { getHrefFromSnapshot, ViewportResolution } from './snapshot-processing/patch-meta-event'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const TWENTY_FOUR_HOURS_IN_MS = 24 * 60 * 60 * 1000 // +- before and after start and end of a recording to query for session linked events.
const FIVE_MINUTES_IN_MS = 5 * 60 * 1000 // +- before and after start and end of a recording to query for events related by person.
const DEFAULT_REALTIME_POLLING_MILLIS = 3000
const DEFAULT_V2_POLLING_INTERVAL_MS = 10000

export interface SessionRecordingDataLogicProps {
    sessionRecordingId: SessionRecordingId
    // allows altering v1 polling interval in tests
    realTimePollingIntervalMilliseconds?: number
    // allows disabling polling for new sources in tests
    blobV2PollingDisabled?: boolean
    playerKey?: string
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecording']],
        values: [
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam'],
            annotationsModel,
            ['annotations', 'annotationsLoading'],
        ],
    })),
    defaults({
        sessionPlayerMetaData: null as SessionRecordingType | null,
    }),
    actions({
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        loadRecordingMeta: true,
        loadRecordingComments: true,
        maybeLoadRecordingMeta: true,
        loadSnapshots: true,
        loadSnapshotSources: (breakpointLength?: number) => ({ breakpointLength }),
        loadNextSnapshotSource: true,
        loadSnapshotsForSource: (sources: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'>[]) => ({
            sources,
        }),
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType | RecordingEventType[]) => ({ event }),
        markViewed: (delay?: number) => ({ delay }),
        reportUsageIfFullyLoaded: true,
        persistRecording: true,
        maybePersistRecording: true,
        pollRealtimeSnapshots: true,
        stopRealtimePolling: true,
        setTrackedWindow: (windowId: string | null) => ({ windowId }),
        setWasMarkedViewed: (wasMarkedViewed: boolean) => ({ wasMarkedViewed }),
    }),
    reducers(() => ({
        trackedWindow: [
            null as string | null,
            {
                setTrackedWindow: (_, { windowId }) => windowId,
            },
        ],
        filters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        isRealtimePolling: [
            false as boolean,
            {
                pollRealtimeSnapshots: () => true,
                stopRealtimePolling: () => false,
            },
        ],
        isNotFound: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: () => true,
            },
        ],
        snapshotsBySourceSuccessCount: [
            0,
            {
                loadSnapshotsForSourceSuccess: (state) => state + 1,
            },
        ],
        wasMarkedViewed: [
            false as boolean,
            {
                setWasMarkedViewed: (_, { wasMarkedViewed }) => wasMarkedViewed,
            },
        ],
    })),
    loaders(({ values, props, cache }) => ({
        sessionComments: {
            loadRecordingComments: async (_, breakpoint) => {
                const empty: RecordingComment[] = []
                if (!props.sessionRecordingId) {
                    return empty
                }

                const response = await api.notebooks.recordingComments(props.sessionRecordingId)
                breakpoint()

                return response.results || empty
            },
        },
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                if (!props.sessionRecordingId) {
                    return null
                }

                const response = await api.recordings.get(props.sessionRecordingId)
                breakpoint()

                return response
            },

            persistRecording: async (_, breakpoint) => {
                if (!values.sessionPlayerMetaData) {
                    return null
                }
                await breakpoint(100)
                await api.recordings.persist(props.sessionRecordingId)

                return {
                    ...values.sessionPlayerMetaData,
                    storage: 'object_storage_lts',
                }
            },
        },
        snapshotSources: [
            null as SessionRecordingSnapshotSource[] | null,
            {
                loadSnapshotSources: async ({ breakpointLength }, breakpoint) => {
                    if (breakpointLength) {
                        await breakpoint(breakpointLength)
                    }
                    const blob_v2 = values.featureFlags[FEATURE_FLAGS.RECORDINGS_BLOBBY_V2_REPLAY]
                    const response = await api.recordings.listSnapshotSources(props.sessionRecordingId, {
                        blob_v2,
                    })

                    if (!response.sources) {
                        return []
                    }
                    const anyBlobV2 = response.sources.some((s) => s.source === SnapshotSourceType.blob_v2)

                    if (anyBlobV2) {
                        return response.sources.filter((s) => s.source === SnapshotSourceType.blob_v2)
                    }
                    return response.sources.filter((s) => s.source !== SnapshotSourceType.blob_v2)
                },
            },
        ],
        snapshotsForSource: [
            null as SessionRecordingSnapshotSourceResponse | null,
            {
                loadSnapshotsForSource: async ({ sources }, breakpoint) => {
                    let params: SessionRecordingSnapshotParams

                    if (sources.length > 1) {
                        // they all have to be blob_v2
                        if (sources.some((s) => s.source !== SnapshotSourceType.blob_v2)) {
                            throw new Error('Unsupported source for multiple sources')
                        }
                        params = {
                            source: 'blob_v2',
                            // so the caller has to make sure these are in order!
                            start_blob_key: sources[0].blob_key,
                            end_blob_key: sources[sources.length - 1].blob_key,
                        }
                    } else {
                        const source = sources[0]

                        if (source.source === SnapshotSourceType.blob) {
                            if (!source.blob_key) {
                                throw new Error('Missing key')
                            }
                            params = { blob_key: source.blob_key, source: 'blob' }
                        } else if (source.source === SnapshotSourceType.realtime) {
                            params = { source: 'realtime' }
                        } else if (source.source === SnapshotSourceType.blob_v2) {
                            params = { source: 'blob_v2', blob_key: source.blob_key }
                        } else if (source.source === SnapshotSourceType.file) {
                            // no need to load a file source, it is already loaded
                            return { source }
                        } else {
                            throw new Error(`Unsupported source: ${source.source}`)
                        }
                    }

                    await breakpoint(1)

                    const response = await api.recordings.getSnapshots(props.sessionRecordingId, params).catch((e) => {
                        if (sources[0].source === 'realtime' && e.status === 404) {
                            // Realtime source is not always available, so a 404 is expected
                            return []
                        }
                        throw e
                    })

                    // sorting is very cheap for already sorted lists
                    const parsedSnapshots = (await parseEncodedSnapshots(response, props.sessionRecordingId)).sort(
                        (a, b) => a.timestamp - b.timestamp
                    )
                    // we store the data in the cache because we want to avoid copying this data as much as possible
                    // and kea's immutability means we were copying all of the data on every snapshot call
                    cache.snapshotsBySource = cache.snapshotsBySource || {}
                    // it doesn't matter which source we use as the key, since we combine the snapshots anyway
                    cache.snapshotsBySource[keyForSource(sources[0])] = { snapshots: parsedSnapshots }
                    // but we do want to mark the sources as loaded
                    sources.forEach((s) => {
                        const k = keyForSource(s)
                        // we just need something against each key so we don't load it again
                        cache.snapshotsBySource[k] = cache.snapshotsBySource[k] || {}
                        cache.snapshotsBySource[k].sourceLoaded = true
                    })

                    return { sources: sources }
                },
            },
        ],
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    const { start, end, person } = values.sessionPlayerData

                    if (!person || !start || !end) {
                        return null
                    }

                    const sessionEventsQuery = hogql`
SELECT uuid, event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type, properties.$viewport_width, properties.$viewport_height, properties.$screen_name
FROM events
WHERE timestamp > ${start.subtract(TWENTY_FOUR_HOURS_IN_MS, 'ms')}
AND timestamp < ${end.add(TWENTY_FOUR_HOURS_IN_MS, 'ms')}
AND $session_id = ${props.sessionRecordingId}
ORDER BY timestamp ASC
LIMIT 1000000`

                    let relatedEventsQuery = hogql`
SELECT uuid, event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type
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
    listeners(({ values, actions, cache, props }) => ({
        loadSnapshots: () => {
            // This kicks off the loading chain
            if (!values.snapshotSourcesLoading) {
                actions.loadSnapshotSources()
            }
        },
        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
            if (!values.sessionCommentsLoading) {
                actions.loadRecordingComments()
            }
        },
        loadSnapshotSources: () => {
            // We only load events once we actually start loading the recording
            if (!values.sessionEventsData) {
                actions.loadEvents()
            }
        },
        loadRecordingMetaSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadSnapshotSourcesSuccess: () => {
            // When we receive the list of sources, we can kick off the loading chain
            actions.loadNextSnapshotSource()
        },

        loadSnapshotsForSourceSuccess: ({ snapshotsForSource }) => {
            const sources = values.snapshotSources
            const sourceKey = snapshotsForSource.sources
                ? keyForSource(snapshotsForSource.sources[0])
                : keyForSource(snapshotsForSource.source)
            const snapshots = (cache.snapshotsBySource || {})[sourceKey] || []

            // Cache the last response count to detect if we're getting the same data over and over
            const newSnapshotsCount = snapshots.length

            if ((cache.lastSnapshotsCount ?? newSnapshotsCount) === newSnapshotsCount) {
                // if we're getting no results from realtime polling, we can increment faster
                // so that we stop polling sooner
                const increment = newSnapshotsCount === 0 ? 2 : 1
                cache.lastSnapshotsUnchangedCount = (cache.lastSnapshotsUnchangedCount ?? 0) + increment
            } else {
                cache.lastSnapshotsUnchangedCount = 0
            }
            cache.lastSnapshotsCount = newSnapshotsCount

            if (!snapshots.length && sources?.length === 1 && sources[0].source !== SnapshotSourceType.file) {
                // We got only a single source to load, loaded it successfully, but it had no snapshots.
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })
            }
            if (!values.wasMarkedViewed) {
                actions.markViewed()
            }

            actions.loadNextSnapshotSource()
        },

        loadNextSnapshotSource: () => {
            // yes this is ugly duplication but we're going to deprecate v1 and I want it to be clear which is which
            if (values.snapshotSources?.some((s) => s.source === SnapshotSourceType.blob_v2)) {
                const nextSourcesToLoad =
                    values.snapshotSources?.filter((s) => {
                        const sourceKey = keyForSource(s)
                        return (
                            !cache.snapshotsBySource?.[sourceKey]?.sourceLoaded && s.source !== SnapshotSourceType.file
                        )
                    }) || []

                if (nextSourcesToLoad.length > 0) {
                    return actions.loadSnapshotsForSource(nextSourcesToLoad.slice(0, 30))
                }

                if (!props.blobV2PollingDisabled) {
                    actions.loadSnapshotSources(DEFAULT_V2_POLLING_INTERVAL_MS)
                }
            } else {
                const nextSourceToLoad = values.snapshotSources?.find((s) => {
                    const sourceKey = keyForSource(s)
                    return !cache.snapshotsBySource?.[sourceKey]?.sourceLoaded && s.source !== SnapshotSourceType.file
                })

                if (nextSourceToLoad) {
                    return actions.loadSnapshotsForSource([nextSourceToLoad])
                }

                // If we have a realtime source, start polling it
                const realTimeSource = values.snapshotSources?.find((s) => s.source === SnapshotSourceType.realtime)
                if (realTimeSource) {
                    actions.pollRealtimeSnapshots()
                }
            }

            actions.reportUsageIfFullyLoaded()
        },
        pollRealtimeSnapshots: () => {
            // always make sure we've cleared up the last timeout
            clearTimeout(cache.realTimePollingTimeoutID)
            cache.realTimePollingTimeoutID = null

            // ten is an arbitrary limit to try to avoid sending requests to our backend unnecessarily
            // we could change this or add to it e.g. only poll if browser is visible to user
            if ((cache.lastSnapshotsUnchangedCount ?? 0) <= 10) {
                cache.realTimePollingTimeoutID = setTimeout(() => {
                    actions.loadSnapshotsForSource([{ source: SnapshotSourceType.realtime }])
                }, props.realTimePollingIntervalMilliseconds || DEFAULT_REALTIME_POLLING_MILLIS)
            } else {
                actions.stopRealtimePolling()
            }
        },
        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        reportUsageIfFullyLoaded: (_, breakpoint) => {
            breakpoint()
            if (values.fullyLoaded) {
                actions.reportRecording(
                    values.sessionPlayerData,
                    SessionRecordingUsageType.LOADED,
                    values.sessionPlayerMetaData,
                    0
                )
            }
        },
        markViewed: async ({ delay }, breakpoint) => {
            // Triggered on first paint
            breakpoint()
            if (props.playerKey?.startsWith('file-')) {
                return
            }
            if (values.wasMarkedViewed) {
                return
            }
            actions.setWasMarkedViewed(true) // this prevents us from calling the function multiple times

            await breakpoint(IS_TEST_MODE ? 1 : delay ?? 3000)
            await api.recordings.update(props.sessionRecordingId, {
                viewed: true,
                player_metadata: values.sessionPlayerMetaData,
            })
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            await api.recordings.update(props.sessionRecordingId, {
                analyzed: true,
                player_metadata: values.sessionPlayerMetaData,
            })
        },

        maybePersistRecording: () => {
            if (values.sessionPlayerMetaDataLoading) {
                return
            }

            if (values.sessionPlayerMetaData?.storage === 'object_storage') {
                actions.persistRecording()
            }
        },
    })),
    selectors(({ cache }) => ({
        sessionAnnotations: [
            (s) => [s.annotations, s.start, s.end],
            (annotations, start, end): InspectorListItemAnnotationComment[] => {
                const allowedScopes = [AnnotationScope.Recording, AnnotationScope.Project, AnnotationScope.Organization]
                const startValue = start?.valueOf()
                const endValue = end?.valueOf()

                const result: InspectorListItemAnnotationComment[] = []
                for (const annotation of annotations) {
                    if (!allowedScopes.includes(annotation.scope)) {
                        continue
                    }

                    if (!annotation.date_marker || !startValue || !endValue || !annotation.content) {
                        continue
                    }

                    const annotationTime = dayjs(annotation.date_marker).valueOf()
                    if (annotationTime < startValue || annotationTime > endValue) {
                        continue
                    }

                    result.push({
                        type: 'comment',
                        source: 'annotation',
                        data: annotation,
                        timestamp: dayjs(annotation.date_marker),
                        timeInRecording: annotation.date_marker.valueOf() - startValue,
                        search: annotation.content,
                        highlightColor: 'primary',
                    })
                }

                return result
            },
        ],
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
        windowIdForTimestamp: [
            (s) => [s.segments],
            (segments) =>
                (timestamp: number): string | undefined => {
                    cache.windowIdForTimestamp = cache.windowIdForTimestamp || {}
                    if (cache.windowIdForTimestamp[timestamp]) {
                        return cache.windowIdForTimestamp[timestamp]
                    }
                    const matchingWindowId = segments.find(
                        (segment) => segment.startTimestamp <= timestamp && segment.endTimestamp >= timestamp
                    )?.windowId

                    cache.windowIdForTimestamp[timestamp] = matchingWindowId
                    return matchingWindowId
                },
        ],
        eventViewports: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): (ViewportResolution & { timestamp: string | number })[] =>
                (sessionEventsData || [])
                    .filter((e) => e.properties.$viewport_width && e.properties.$viewport_height)
                    .map((e) => ({
                        width: e.properties.$viewport_width,
                        height: e.properties.$viewport_height,
                        href: e.properties.$current_url,
                        timestamp: e.timestamp,
                    })),
        ],
        viewportForTimestamp: [
            (s) => [s.eventViewports],
            (eventViewports) =>
                (timestamp: number): ViewportResolution | undefined => {
                    // we do this as a function because in most recordings we don't need the data, so we don't need to run this every time

                    cache.viewportForTimestamp = cache.viewportForTimestamp || {}
                    if (cache.viewportForTimestamp[timestamp]) {
                        return cache.viewportForTimestamp[timestamp]
                    }

                    let result: ViewportResolution | undefined

                    // First, try to find the first event after the timestamp that has viewport dimensions
                    const nextEvent = eventViewports
                        .filter((e) => dayjs(e.timestamp).isSameOrAfter(dayjs(timestamp)))
                        .sort((a, b) => dayjs(a.timestamp).valueOf() - dayjs(b.timestamp).valueOf())[0]

                    if (nextEvent) {
                        result = {
                            width: nextEvent.width,
                            height: nextEvent.height,
                            href: nextEvent.href,
                        }
                    } else {
                        // If no event after timestamp, find the closest event before it
                        const previousEvent = eventViewports
                            .filter((e) => dayjs(e.timestamp).isBefore(dayjs(timestamp)))
                            .sort((a, b) => dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf())[0] // Sort descending to get closest

                        if (previousEvent) {
                            result = {
                                width: previousEvent.width,
                                height: previousEvent.height,
                                href: previousEvent.href,
                            }
                        }
                    }

                    if (result) {
                        cache.viewportForTimestamp[timestamp] = result
                    }

                    return result
                },
        ],
        sessionPlayerData: [
            (s, p) => [
                s.sessionPlayerMetaData,
                s.snapshotsByWindowId,
                s.segments,
                s.bufferedToTime,
                s.start,
                s.end,
                s.durationMs,
                s.fullyLoaded,
                p.sessionRecordingId,
            ],
            (
                meta,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                start,
                end,
                durationMs,
                fullyLoaded,
                sessionRecordingId
            ): SessionPlayerData => ({
                person: meta?.person ?? null,
                start,
                end,
                durationMs,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                fullyLoaded,
                sessionRecordingId,
            }),
        ],

        snapshotsLoading: [
            (s) => [s.snapshotSourcesLoading, s.snapshotsForSourceLoading, s.snapshots, s.featureFlags],
            (
                snapshotSourcesLoading: boolean,
                snapshotsForSourceLoading: boolean,
                snapshots: RecordingSnapshot[],
                featureFlags: FeatureFlagsSet
            ): boolean => {
                // For v2 recordings, only show loading if we have no snapshots yet
                if (featureFlags[FEATURE_FLAGS.RECORDINGS_BLOBBY_V2_REPLAY]) {
                    return snapshots.length === 0
                }

                // Default behavior for non-v2 recordings
                // if there's a realTimePollingTimeoutID, don't signal that we're loading
                // we don't want the UI to flip to "loading" every time we poll
                return !cache.realTimePollingTimeoutID && (snapshotSourcesLoading || snapshotsForSourceLoading)
            },
        ],

        snapshotsLoaded: [(s) => [s.snapshotSources], (snapshotSources): boolean => !!snapshotSources],

        fullyLoaded: [
            (s) => [s.snapshots, s.sessionPlayerMetaDataLoading, s.snapshotsLoading, s.sessionEventsDataLoading],
            (snapshots, sessionPlayerMetaDataLoading, snapshotsLoading, sessionEventsDataLoading): boolean => {
                // TODO: Do a proper check for all sources having been loaded
                return (
                    !!snapshots?.length &&
                    !sessionPlayerMetaDataLoading &&
                    !snapshotsLoading &&
                    !sessionEventsDataLoading
                )
            },
        ],

        firstSnapshot: [
            (s) => [s.snapshots],
            (snapshots): RecordingSnapshot | null => {
                return snapshots[0] || null
            },
        ],

        lastSnapshot: [
            (s) => [s.snapshots],
            (snapshots): RecordingSnapshot | null => {
                return snapshots[snapshots.length - 1] || null
            },
        ],

        start: [
            (s) => [s.firstSnapshot, s.sessionPlayerMetaData],
            (firstSnapshot, meta): Dayjs | null => {
                const eventStart = meta?.start_time ? dayjs(meta.start_time) : null
                const snapshotStart = firstSnapshot ? dayjs(firstSnapshot.timestamp) : null

                // whichever is earliest
                if (eventStart && snapshotStart) {
                    return eventStart.isBefore(snapshotStart) ? eventStart : snapshotStart
                }
                return eventStart || snapshotStart
            },
        ],

        end: [
            (s) => [s.lastSnapshot, s.sessionPlayerMetaData],
            (lastSnapshot, meta): Dayjs | null => {
                const eventEnd = meta?.end_time ? dayjs(meta.end_time) : null
                const snapshotEnd = lastSnapshot ? dayjs(lastSnapshot.timestamp) : null

                // whichever is latest
                if (eventEnd && snapshotEnd) {
                    return eventEnd.isAfter(snapshotEnd) ? eventEnd : snapshotEnd
                }
                return eventEnd || snapshotEnd
            },
        ],

        durationMs: [
            (s) => [s.start, s.end],
            (start, end): number => {
                return !!start && !!end ? end.diff(start) : 0
            },
        ],

        segments: [
            (s) => [s.snapshots, s.start, s.end, s.trackedWindow],
            (snapshots, start, end, trackedWindow): RecordingSegment[] => {
                return createSegments(snapshots || [], start, end, trackedWindow)
            },
        ],

        urls: [
            (s) => [s.snapshots],
            (snapshots): { url: string; timestamp: number }[] => {
                return (
                    snapshots
                        .filter((snapshot) => getHrefFromSnapshot(snapshot))
                        .map((snapshot) => {
                            return {
                                url: getHrefFromSnapshot(snapshot) as string,
                                timestamp: snapshot.timestamp,
                            }
                        }) ?? []
                )
            },
        ],

        snapshots: [
            (s, p) => [
                s.snapshotSources,
                s.viewportForTimestamp,
                p.sessionRecordingId,
                s.snapshotsBySourceSuccessCount,
            ],
            (
                sources,
                viewportForTimestamp,
                sessionRecordingId,
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                _snapshotsBySourceSuccessCount
            ): RecordingSnapshot[] => {
                if (!sources || !cache.snapshotsBySource) {
                    return []
                }
                const processedSnapshots = processAllSnapshots(
                    sources,
                    cache.snapshotsBySource || {},
                    viewportForTimestamp,
                    sessionRecordingId
                )
                return processedSnapshots['processed'].snapshots || []
            },
        ],

        snapshotsRaw: [
            (s) => [s.snapshotSources, s.viewportForTimestamp],
            (
                sources,
                // eslint-disable-next-line @typescript-eslint/no-unused-vars
                _snapshotsBySourceSuccessCount
            ): RecordingSnapshot[] => {
                if (!sources || !cache.snapshotsBySource) {
                    return []
                }

                const processedSnapshots = processAllSnapshotsRaw(sources, cache.snapshotsBySource || {})
                return processedSnapshots || []
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.snapshots],
            (snapshots): Record<string, eventWithTime[]> => {
                return mapSnapshotsToWindowId(snapshots || [])
            },
        ],

        snapshotsInvalid: [
            (s, p) => [s.snapshotsByWindowId, s.fullyLoaded, s.start, p.sessionRecordingId, s.currentTeam],
            (snapshotsByWindowId, fullyLoaded, start, sessionRecordingId, currentTeam): boolean => {
                if (!fullyLoaded || !start) {
                    return false
                }

                const windowsHaveFullSnapshot = Object.entries(snapshotsByWindowId).reduce(
                    (acc, [windowId, events]) => {
                        acc[`window-id-${windowId}-has-full-snapshot`] = events.some(
                            (event) => event.type === EventType.FullSnapshot
                        )
                        return acc
                    },
                    {}
                )
                const anyWindowMissingFullSnapshot = !Object.values(windowsHaveFullSnapshot).some((x) => x)
                const everyWindowMissingFullSnapshot = !Object.values(windowsHaveFullSnapshot).every((x) => x)

                if (everyWindowMissingFullSnapshot) {
                    // video is definitely unplayable
                    posthog.capture('recording_has_no_full_snapshot', {
                        watchedSession: sessionRecordingId,
                        teamId: currentTeam?.id,
                        teamName: currentTeam?.name,
                    })
                } else if (anyWindowMissingFullSnapshot) {
                    posthog.capture('recording_window_missing_full_snapshot', {
                        watchedSession: sessionRecordingId,
                        teamID: currentTeam?.id,
                        teamName: currentTeam?.name,
                    })
                }

                return everyWindowMissingFullSnapshot
            },
        ],

        isRecentAndInvalid: [
            (s) => [s.start, s.snapshotsInvalid],
            (start, snapshotsInvalid) => {
                const lessThanFiveMinutesOld = dayjs().diff(start, 'minute') <= 5
                return snapshotsInvalid && lessThanFiveMinutesOld
            },
        ],

        isLikelyPastTTL: [
            (s) => [s.start, s.snapshotSources],
            (start, snapshotSources) => {
                // If the recording is older than 30 days and has only realtime sources being reported, it is likely past its TTL
                const isOlderThan30Days = dayjs().diff(start, 'hour') > 30
                const onlyHasRealTime = snapshotSources?.every((s) => s.source === SnapshotSourceType.realtime)
                const hasNoSources = snapshotSources?.length === 0
                return isOlderThan30Days && (onlyHasRealTime || hasNoSources)
            },
        ],

        bufferedToTime: [
            (s) => [s.segments],
            (segments): number | null => {
                if (!segments.length) {
                    return null
                }

                const startTime = segments[0].startTimestamp
                const lastSegment = segments[segments.length - 1]

                if (lastSegment.kind === 'buffer') {
                    return lastSegment.startTimestamp - startTime
                }

                return lastSegment.endTimestamp - startTime
            },
        ],

        windowIds: [
            (s) => [s.snapshotsByWindowId],
            (snapshotsByWindowId) => {
                return Object.keys(snapshotsByWindowId)
            },
        ],

        createExportJSON: [
            (s) => [s.sessionPlayerMetaData, s.snapshots],
            (
                sessionPlayerMetaData,
                snapshots
            ): ((type?: ExportedSessionType) => ExportedSessionRecordingFileV2 | RecordingSnapshot[]) => {
                return (type?: ExportedSessionType) => {
                    return type === 'rrweb'
                        ? snapshots
                        : {
                              version: '2023-04-28',
                              data: {
                                  id: sessionPlayerMetaData?.id ?? '',
                                  person: sessionPlayerMetaData?.person,
                                  snapshots: snapshots,
                              },
                          }
                }
            },
        ],

        customRRWebEvents: [
            (s) => [s.snapshots],
            (snapshots): customEvent[] => {
                return snapshots.filter((snapshot) => snapshot.type === EventType.Custom).map((x) => x as customEvent)
            },
        ],
    })),
    subscriptions(({ actions, values }) => ({
        webVitalsEvents: (value: RecordingEventType[]) => {
            // we preload all web vitals data, so it can be used before user interaction
            if (!values.sessionEventsDataLoading) {
                actions.loadFullEventData(value)
            }
        },
        AIEvents: (value: RecordingEventType[]) => {
            // we preload all AI  data, so it can be used before user interaction
            if (value.length > 0) {
                actions.loadFullEventData(value)
            }
        },
        isRecentAndInvalid: (prev: boolean, next: boolean) => {
            if (!prev && next) {
                posthog.capture('recording cannot playback yet', {
                    watchedSession: values.sessionPlayerData.sessionRecordingId,
                })
            }
        },
    })),
    beforeUnmount(({ cache }) => {
        // Clear the cache

        if (cache.realTimePollingTimeoutID) {
            clearTimeout(cache.realTimePollingTimeoutID)
            cache.realTimePollingTimeoutID = undefined
        }

        cache.windowIdForTimestamp = undefined
        cache.viewportForTimestamp = undefined
        cache.snapshotsBySource = undefined
    }),
])
