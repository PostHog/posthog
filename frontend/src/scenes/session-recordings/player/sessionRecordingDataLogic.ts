import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    EncodedRecordingSnapshot,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionPlayerSnapshotData,
    SessionRecordingId,
    SessionRecordingSnapshotSource,
    SessionRecordingType,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventWithTime } from '@rrweb/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { chainToElements } from 'lib/utils/elements-chain'
import { captureException } from '@sentry/react'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'
import posthog from 'posthog-js'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

const parseEncodedSnapshots = (items: (EncodedRecordingSnapshot | string)[], sessionId: string): RecordingSnapshot[] =>
    items.flatMap((l) => {
        try {
            const snapshotLine = typeof l === 'string' ? (JSON.parse(l) as EncodedRecordingSnapshot) : l
            const snapshotData = snapshotLine['data']

            return snapshotData.map((d: any) => ({
                windowId: snapshotLine['window_id'],
                ...d,
            }))
        } catch (e) {
            posthog.capture('session recording had unparseable line', {
                sessionId,
                line: l,
            })
            captureException(e)
            return []
        }
    })

const getHrefFromSnapshot = (snapshot: RecordingSnapshot): string | undefined => {
    return (snapshot.data as any)?.href || (snapshot.data as any)?.payload?.href
}

export const prepareRecordingSnapshots = (
    newSnapshots?: RecordingSnapshot[],
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    const seenHashes: Record<string, (RecordingSnapshot | string)[]> = {}

    const prepared = (newSnapshots || [])
        .concat(existingSnapshots ? existingSnapshots ?? [] : [])
        .filter((snapshot) => {
            // For a multitude of reasons, there can be duplicate snapshots in the same recording.
            // We can deduplicate by filtering out snapshots with the same timestamp and delay value (this is quite unique as a pairing)
            const key = `${snapshot.timestamp}-${snapshot.delay}`

            if (!seenHashes[key]) {
                seenHashes[key] = [snapshot]
            } else {
                // If we are looking at an identical event time, we stringify the original snapshot if not already stringified,
                // Then stringify the new snapshot and compare the two. If it is the same, we can ignore it.
                seenHashes[key][0] =
                    typeof seenHashes[key][0] === 'string' ? seenHashes[key][0] : JSON.stringify(seenHashes[key][0])
                const newSnapshot = JSON.stringify(snapshot)
                if (seenHashes[key][0] === newSnapshot) {
                    return false
                }
                seenHashes[key].push(snapshot)
            }

            return true
        })
        .sort((a, b) => a.timestamp - b.timestamp)

    return prepared
}

export const convertSnapshotsByWindowId = (snapshotsByWindowId: {
    [key: string]: eventWithTime[]
}): RecordingSnapshot[] => {
    return Object.entries(snapshotsByWindowId).flatMap(([windowId, snapshots]) => {
        return snapshots.map((snapshot) => ({
            ...snapshot,
            windowId,
        }))
    })
}

// Until we change the API to return a simple list of snapshots, we need to convert this ourselves
export const convertSnapshotsResponse = (
    snapshotsByWindowId: { [key: string]: eventWithTime[] },
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    return prepareRecordingSnapshots(convertSnapshotsByWindowId(snapshotsByWindowId), existingSnapshots)
}

const generateRecordingReportDurations = (
    cache: Record<string, any>,
    values: Record<string, any>
): RecordingReportLoadTimes => {
    // TODO: This any typing is super hard to manage - we should either type it or move it to a selector.
    return {
        metadata: {
            size: values.segments.length,
            duration: Math.round(performance.now() - cache.metaStartTime),
        },
        snapshots: {
            size: (values.sessionPlayerSnapshotData?.segments ?? []).length,
            duration: Math.round(performance.now() - cache.snapshotsStartTime),
        },
        events: {
            size: values.sessionEventsData?.length ?? 0,
            duration: Math.round(performance.now() - cache.eventsStartTime),
        },
        firstPaint: cache.firstPaintDurationRow,
    }
}

export interface SessionRecordingDataLogicProps {
    sessionRecordingId: SessionRecordingId
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect({
        logic: [eventUsageLogic],
    }),
    defaults({
        sessionPlayerMetaData: null as SessionRecordingType | null,
    }),
    actions({
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        loadRecordingMeta: true,
        maybeLoadRecordingMeta: true,
        loadRecordingSnapshots: (source?: SessionRecordingSnapshotSource) => ({ source }),
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType) => ({ event }),
        reportViewed: true,
        reportUsageIfFullyLoaded: true,
        persistRecording: true,
        maybePersistRecording: true,
    }),
    reducers(() => ({
        filters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
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
        snapshotsLoaded: [
            false as boolean,
            {
                loadRecordingSnapshotsSuccess: () => true,
                loadRecordingSnapshotsFailure: () => true,
            },
        ],
    })),
    listeners(({ values, actions, cache }) => ({
        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
        },
        loadRecordingSnapshots: () => {
            actions.loadEvents()
        },
        loadRecordingSnapshotsSuccess: () => {
            const { snapshots, sources } = values.sessionPlayerSnapshotData ?? {}
            if (snapshots && !snapshots.length && sources?.length === 1) {
                // We got only a snapshot response for realtime, and it was empty
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })

                return
            }

            cache.firstPaintDurationRow = {
                size: (values.sessionPlayerSnapshotData?.snapshots ?? []).length,
                duration: Math.round(performance.now() - cache.snapshotsStartTime),
            }

            actions.reportViewed()
            actions.reportUsageIfFullyLoaded()

            const nextSourceToLoad = sources?.find((s) => !s.loaded)

            if (nextSourceToLoad) {
                actions.loadRecordingSnapshots(nextSourceToLoad)
            }
        },
        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        reportUsageIfFullyLoaded: () => {
            if (values.fullyLoaded) {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    generateRecordingReportDurations(cache, values),
                    SessionRecordingUsageType.LOADED,
                    0
                )
                // Reset cache now that final usage report has been sent
                cache.metaStartTime = null
                cache.snapshotsStartTime = null
                cache.eventsStartTime = null
                cache.firstPaintDurationRow = null
            }
        },
        reportViewed: async (_, breakpoint) => {
            const durations = generateRecordingReportDurations(cache, values)

            await breakpoint()
            // Triggered on first paint
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.VIEWED,
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.ANALYZED,
                10
            )
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
    loaders(({ values, props, cache }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                cache.metaStartTime = performance.now()
                if (!props.sessionRecordingId) {
                    return null
                }
                const response = await api.recordings.get(props.sessionRecordingId, {
                    save_view: true,
                })
                breakpoint()

                return response
            },

            persistRecording: async (_, breakpoint) => {
                if (!values.sessionPlayerMetaData) {
                    return null
                }
                breakpoint(100)
                await api.recordings.persist(props.sessionRecordingId)

                return {
                    ...values.sessionPlayerMetaData,
                    storage: 'object_storage_lts',
                }
            },
        },
        sessionPlayerSnapshotData: [
            null as SessionPlayerSnapshotData | null,
            {
                loadRecordingSnapshots: async ({ source }, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    if (!props.sessionRecordingId) {
                        return values.sessionPlayerSnapshotData
                    }

                    cache.snapshotsStartTime = performance.now()

                    const data: SessionPlayerSnapshotData = {
                        ...(values.sessionPlayerSnapshotData || {}),
                    }

                    await breakpoint(1)

                    if (source?.source === 'blob') {
                        if (!source.blob_key) {
                            throw new Error('Missing key')
                        }
                        const encodedResponse = await api.recordings.getBlobSnapshots(
                            props.sessionRecordingId,
                            source.blob_key
                        )
                        data.snapshots = prepareRecordingSnapshots(
                            parseEncodedSnapshots(encodedResponse, props.sessionRecordingId),
                            values.sessionPlayerSnapshotData?.snapshots ?? []
                        )
                    } else {
                        const params = toParams({
                            source: source?.source,
                            key: source?.blob_key,
                            version: '2',
                        })
                        const response = await api.recordings.listSnapshots(props.sessionRecordingId, params)
                        if (response.snapshots) {
                            data.snapshots = prepareRecordingSnapshots(
                                parseEncodedSnapshots(response.snapshots, props.sessionRecordingId),
                                values.sessionPlayerSnapshotData?.snapshots ?? []
                            )
                        }

                        if (response.sources) {
                            data.sources = response.sources
                        }
                    }

                    if (source) {
                        source.loaded = true

                        posthog.capture('recording_snapshot_loaded', {
                            source: source.source,
                        })
                    }

                    return data
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

                    const [sessionEvents, relatedEvents]: any[] = await Promise.all(
                        [
                            {
                                key: '$session_id',
                                value: [props.sessionRecordingId],
                                operator: 'exact',
                                type: 'event',
                            },
                            {
                                key: '$session_id',
                                value: '',
                                operator: 'exact',
                                type: 'event',
                            },
                        ].map((properties) =>
                            api.query({
                                kind: 'EventsQuery',
                                // NOTE: Be careful adding fields here. We want to keep the payload as small as possible to load all events quickly
                                select: [
                                    'uuid',
                                    'event',
                                    'timestamp',
                                    'elements_chain',
                                    'properties.$window_id',
                                    'properties.$current_url',
                                    'properties.$event_type',
                                ],
                                orderBy: ['timestamp ASC'],
                                limit: 1000000,
                                personId: String(person.id),
                                after: start.subtract(BUFFER_MS, 'ms').format(),
                                before: end.add(BUFFER_MS, 'ms').format(),
                                properties: [properties],
                            })
                        )
                    )

                    const minimalEvents = [...sessionEvents.results, ...relatedEvents.results].map(
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

                    return minimalEvents
                },

                loadFullEventData: async ({ event }) => {
                    const existingEvent = values.sessionEventsData?.find((x) => x.id === event.id)
                    if (!existingEvent || existingEvent.fullyLoaded) {
                        return values.sessionEventsData
                    }

                    const { person } = values.sessionPlayerData

                    // TODO: Move this to an optimised HogQL query when available...
                    try {
                        const res: any = await api.query({
                            kind: 'EventsQuery',
                            select: ['properties', 'timestamp'],
                            orderBy: ['timestamp ASC'],
                            limit: 100,
                            personId: String(person?.id),
                            after: dayjs(event.timestamp).subtract(1000, 'ms').format(),
                            before: dayjs(event.timestamp).add(1000, 'ms').format(),
                            event: existingEvent.event,
                        })

                        const result = res.results.find((x: any) => x[1] === event.timestamp)

                        if (result) {
                            existingEvent.properties = JSON.parse(result[0])
                            existingEvent.fullyLoaded = true
                        }
                    } catch (e) {
                        // NOTE: This is not ideal but should happen so rarely that it is tolerable.
                        existingEvent.fullyLoaded = true
                        captureException(e)
                    }

                    return values.sessionEventsData
                },
            },
        ],
    })),
    selectors({
        sessionPlayerData: [
            (s) => [
                s.sessionPlayerMetaData,
                s.snapshotsByWindowId,
                s.segments,
                s.bufferedToTime,
                s.start,
                s.end,
                s.durationMs,
                s.fullyLoaded,
            ],
            (
                meta,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                start,
                end,
                durationMs,
                fullyLoaded
            ): SessionPlayerData => ({
                person: meta?.person ?? null,
                start,
                end,
                durationMs,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                fullyLoaded,
            }),
        ],

        fullyLoaded: [
            (s) => [
                s.sessionPlayerSnapshotData,
                s.sessionPlayerMetaDataLoading,
                s.sessionPlayerSnapshotDataLoading,
                s.sessionEventsDataLoading,
            ],
            (
                sessionPlayerSnapshotData,
                sessionPlayerMetaDataLoading,
                sessionPlayerSnapshotDataLoading,
                sessionEventsDataLoading
            ): boolean => {
                return (
                    !!sessionPlayerSnapshotData?.snapshots?.length &&
                    !sessionPlayerMetaDataLoading &&
                    !sessionPlayerSnapshotDataLoading &&
                    !sessionEventsDataLoading
                )
            },
        ],

        start: [
            (s) => [s.sessionPlayerMetaData],
            (meta): Dayjs | undefined => {
                return meta?.start_time ? dayjs(meta.start_time) : undefined
            },
        ],

        end: [
            (s) => [s.sessionPlayerMetaData, s.sessionPlayerSnapshotData],
            (meta, sessionPlayerSnapshotData): Dayjs | undefined => {
                // NOTE: We might end up with more snapshots than we knew about when we started the recording so we
                // either use the metadata end point or the last snapshot, whichever is later.
                const end = meta?.end_time ? dayjs(meta.end_time) : undefined
                const lastEvent = sessionPlayerSnapshotData?.snapshots?.slice(-1)[0]

                return lastEvent?.timestamp && lastEvent.timestamp > +(end ?? 0) ? dayjs(lastEvent.timestamp) : end
            },
        ],

        durationMs: [
            (s) => [s.start, s.end],
            (start, end): number => {
                return end?.diff(start) ?? 0
            },
        ],

        segments: [
            (s) => [s.sessionPlayerSnapshotData, s.start, s.end],
            (sessionPlayerSnapshotData, start, end): RecordingSegment[] => {
                return createSegments(sessionPlayerSnapshotData?.snapshots || [], start, end)
            },
        ],

        urls: [
            (s) => [s.sessionPlayerSnapshotData],
            (sessionPlayerSnapshotData): { url: string; timestamp: number }[] => {
                return (
                    sessionPlayerSnapshotData?.snapshots
                        ?.filter((snapshot) => getHrefFromSnapshot(snapshot))
                        .map((snapshot) => {
                            return {
                                url: getHrefFromSnapshot(snapshot) as string,
                                timestamp: snapshot.timestamp,
                            }
                        }) ?? []
                )
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.sessionPlayerSnapshotData],
            (sessionPlayerSnapshotData): Record<string, eventWithTime[]> => {
                return mapSnapshotsToWindowId(sessionPlayerSnapshotData?.snapshots || [])
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
    }),
])
