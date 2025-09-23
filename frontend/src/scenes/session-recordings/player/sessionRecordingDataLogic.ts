import { actions, beforeUnmount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { EventType, customEvent, eventWithTime } from '@posthog/rrweb-types'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { chainToElements } from 'lib/utils/elements-chain'
import { TimeTree } from 'lib/utils/time-tree'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import { RecordingComment } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import {
    ProcessingCache,
    processAllSnapshots,
} from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { teamLogic } from 'scenes/teamLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { HogQLQueryString, hogql } from '~/queries/utils'
import {
    CommentType,
    RecordingEventType,
    RecordingEventsFilters,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionRecordingId,
    SessionRecordingType,
} from '~/types'

import { ExportedSessionRecordingFileV2 } from '../file-playback/types'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { ViewportResolution, getHrefFromSnapshot } from './snapshot-processing/patch-meta-event'
import { snapshotDataLogic } from './snapshotDataLogic'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

const TWENTY_FOUR_HOURS_IN_MS = 24 * 60 * 60 * 1000 // +- before and after start and end of a recording to query for session linked events.
const FIVE_MINUTES_IN_MS = 5 * 60 * 1000 // +- before and after start and end of a recording to query for events related by person.

export interface SessionRecordingDataLogicProps {
    sessionRecordingId: SessionRecordingId
    // allows disabling polling for new sources in tests
    blobV2PollingDisabled?: boolean
    playerKey?: string
    accessToken?: string
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect(({ sessionRecordingId, blobV2PollingDisabled }: SessionRecordingDataLogicProps) => {
        const snapshotLogic = snapshotDataLogic({
            sessionRecordingId,
            blobV2PollingDisabled,
        })
        return {
            actions: [
                sessionRecordingEventUsageLogic,
                ['reportRecordingLoaded'],
                snapshotLogic,
                ['loadSnapshots', 'loadSnapshotSources', 'loadNextSnapshotSource', 'setSnapshots'],
            ],
            values: [
                teamLogic,
                ['currentTeam'],
                annotationsModel,
                ['annotations', 'annotationsLoading'],
                snapshotLogic,
                ['snapshotSources', 'snapshotsBySources', 'snapshotsLoading', 'snapshotsLoaded'],
            ],
        }
    }),
    defaults({
        sessionPlayerMetaData: null as SessionRecordingType | null,
    }),
    actions({
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        loadRecordingMeta: true,
        loadRecordingFromFile: (recording: ExportedSessionRecordingFileV2['data']) => ({ recording }),
        maybeLoadRecordingMeta: true,
        loadRecordingComments: true,
        loadRecordingNotebookComments: true,
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType | RecordingEventType[]) => ({ event }),
        reportUsageIfFullyLoaded: true,
        persistRecording: true,
        maybePersistRecording: true,
        setTrackedWindow: (windowId: string | null) => ({ windowId }),
        setRecordingReportedLoaded: true,
    }),
    reducers(() => ({
        isNotFound: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: () => true,
            },
        ],
        reportedLoaded: [
            false,
            {
                setRecordingReportedLoaded: () => true,
            },
        ],
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
    })),
    loaders(({ values, props }) => ({
        sessionComments: [
            [] as CommentType[],
            {
                loadRecordingComments: async (_, breakpoint): Promise<CommentType[]> => {
                    const empty: CommentType[] = []
                    if (!props.sessionRecordingId) {
                        return empty
                    }

                    const response = await api.comments.list({ item_id: props.sessionRecordingId })
                    breakpoint()

                    return response.results || empty
                },
                deleteComment: async (id, breakpoint): Promise<CommentType[]> => {
                    await breakpoint(25)
                    await api.comments.delete(id)
                    return values.sessionComments.filter((sc) => sc.id !== id)
                },
            },
        ],
        sessionNotebookComments: {
            loadRecordingNotebookComments: async (_, breakpoint) => {
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
                const headers: Record<string, string> = {}
                if (props.accessToken) {
                    headers.Authorization = `Bearer ${props.accessToken}`
                }
                const response = await api.recordings.get(props.sessionRecordingId, {}, headers)
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
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    const { start, end, person } = values.sessionPlayerData

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
    listeners(({ values, actions, props }) => ({
        deleteCommentSuccess: () => {
            lemonToast.success('Comment deleted')
        },

        deleteCommentFailure: (e) => {
            posthog.captureException(e, { action: 'session recording data logic delete comment' })
            lemonToast.error('Could not delete comment, refresh and try again')
        },

        [playerCommentModel.actionTypes.commentEdited]: ({ recordingId }) => {
            if (props.sessionRecordingId === recordingId) {
                actions.loadRecordingComments()
            }
        },

        loadRecordingFromFile: ({ recording }: { recording: ExportedSessionRecordingFileV2['data'] }) => {
            const { id, snapshots, person } = recording
            actions.setSnapshots(snapshots)
            actions.loadRecordingMetaSuccess({
                id,
                viewed: false,
                viewers: [],
                recording_duration: snapshots[snapshots.length - 1].timestamp - snapshots[0].timestamp,
                person: person || undefined,
                start_time: dayjs(snapshots[0].timestamp).toISOString(),
                end_time: dayjs(snapshots[snapshots.length - 1].timestamp).toISOString(),
                snapshot_source: 'unknown', // TODO: we should be able to detect this from the file
            })
        },

        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
            if (!values.sessionCommentsLoading) {
                actions.loadRecordingComments()
            }
            if (!values.sessionNotebookCommentsLoading) {
                actions.loadRecordingNotebookComments()
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

        loadNextSnapshotSource: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        reportUsageIfFullyLoaded: (_, breakpoint) => {
            breakpoint()
            if (values.fullyLoaded && !values.reportedLoaded) {
                actions.setRecordingReportedLoaded()
                actions.reportRecordingLoaded(values.sessionPlayerData, values.sessionPlayerMetaData)
            }
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
                sessionRetentionPeriodDays: meta?.retention_period_days ?? null,
            }),
        ],

        fullyLoaded: [
            (s) => [
                s.snapshots,
                s.sessionPlayerMetaDataLoading,
                s.snapshotsLoading,
                s.sessionEventsDataLoading,
                s.sessionCommentsLoading,
                s.sessionNotebookCommentsLoading,
            ],
            (
                snapshots,
                sessionPlayerMetaDataLoading,
                snapshotsLoading,
                sessionEventsDataLoading,
                sessionCommentsLoading,
                sessionNotebookCommentsLoading
            ): boolean => {
                // TODO: Do a proper check for all sources having been loaded
                return (
                    !!snapshots?.length &&
                    !sessionPlayerMetaDataLoading &&
                    !snapshotsLoading &&
                    !sessionEventsDataLoading &&
                    !sessionCommentsLoading &&
                    !sessionNotebookCommentsLoading
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
            (s, p) => [s.snapshotSources, s.viewportForTimestamp, p.sessionRecordingId, s.snapshotsBySources],
            (
                sources,
                viewportForTimestamp,
                sessionRecordingId,
                // oxlint-disable-next-line @typescript-eslint/no-unused-vars
                snapshotsBySources
            ): RecordingSnapshot[] => {
                cache.processingCache = cache.processingCache || ({} as ProcessingCache)
                const snapshots = processAllSnapshots(
                    sources,
                    snapshotsBySources,
                    cache.processingCache,
                    viewportForTimestamp,
                    sessionRecordingId
                )
                return snapshots || []
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
            (sessionPlayerMetaData, snapshots): (() => ExportedSessionRecordingFileV2) => {
                return (): ExportedSessionRecordingFileV2 => {
                    return {
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
        sessionEventsData: (sed: null | RecordingEventType[]) => {
            const preloadEventTypes = ['$web_vitals', '$ai_', '$exception']
            const preloadableEvents = (sed || []).filter((e) =>
                preloadEventTypes.some((pet) => e.event.startsWith(pet))
            )
            if (preloadableEvents.length) {
                actions.loadFullEventData(preloadableEvents)
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
        cache.windowIdForTimestamp = undefined
        cache.viewportForTimestamp = undefined
        cache.processingCache = undefined
    }),
])
