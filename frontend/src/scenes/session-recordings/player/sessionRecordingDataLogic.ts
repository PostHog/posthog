import posthogEE from '@posthog/ee/exports'
import { EventType, eventWithTime } from '@rrweb/types'
import { captureException } from '@sentry/react'
import {
    actions,
    afterMount,
    beforeUnmount,
    BreakPointFunction,
    connect,
    defaults,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { chainToElements } from 'lib/utils/elements-chain'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'

import { NodeKind } from '~/queries/schema'
import {
    AnyPropertyFilter,
    EncodedRecordingSnapshot,
    PersonType,
    PropertyFilterType,
    PropertyOperator,
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
    SnapshotSourceType,
} from '~/types'

import { PostHogEE } from '../../../../@posthog/ee/types'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.
const DEFAULT_REALTIME_POLLING_MILLIS = 3000
const REALTIME_POLLING_PARAMS = toParams({
    source: SnapshotSourceType.realtime,
    version: '2',
})

let postHogEEModule: PostHogEE

function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[],
    sessionId: string,
    withMobileTransformer: boolean
): Promise<RecordingSnapshot[]> => {
    if (!postHogEEModule && withMobileTransformer) {
        postHogEEModule = await posthogEE()
    }
    const lineCount = items.length
    const unparseableLines: string[] = []
    const parsedLines = items.flatMap((l) => {
        if (!l) {
            // blob files have an empty line at the end
            return []
        }
        try {
            const snapshotLine = typeof l === 'string' ? (JSON.parse(l) as EncodedRecordingSnapshot) : l
            const snapshotData = isRecordingSnapshot(snapshotLine) ? [snapshotLine] : snapshotLine['data']

            return snapshotData.map((d: unknown) => {
                const snap = withMobileTransformer
                    ? postHogEEModule?.mobileReplay?.transformEventToWeb(d) || (d as eventWithTime)
                    : (d as eventWithTime)
                return {
                    // this handles parsing data that was loaded from blob storage "window_id"
                    // and data that was exported from the front-end "windowId"
                    // we have more than one format of data that we store/pass around
                    // but only one that we play back
                    windowId: snapshotLine['window_id'] || snapshotLine['windowId'],
                    ...(snap || (d as eventWithTime)),
                }
            })
        } catch (e) {
            if (typeof l === 'string') {
                unparseableLines.push(l)
            }
            return []
        }
    })

    if (unparseableLines.length) {
        const extra = {
            playbackSessionId: sessionId,
            totalLineCount: lineCount,
            unparseableLinesCount: unparseableLines.length,
            exampleLines: unparseableLines.slice(0, 3),
        }
        posthog.capture('session recording had unparseable lines', extra)
        captureException(new Error('session recording had unparseable lines'), {
            tags: { feature: 'session-recording-snapshot-processing' },
            extra,
        })
    }

    return parsedLines
}

const getHrefFromSnapshot = (snapshot: RecordingSnapshot): string | undefined => {
    return (snapshot.data as any)?.href || (snapshot.data as any)?.payload?.href
}

export const prepareRecordingSnapshots = (
    newSnapshots?: RecordingSnapshot[],
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    const seenHashes: Set<string> = new Set()

    return (newSnapshots || [])
        .concat(existingSnapshots ? existingSnapshots ?? [] : [])
        .filter((snapshot) => {
            // For a multitude of reasons, there can be duplicate snapshots in the same recording.
            // we have to stringify the snapshot to compare it to other snapshots.
            // so we can filter by storing them all in a set

            const key = JSON.stringify(snapshot)
            if (seenHashes.has(key)) {
                return false
            } else {
                seenHashes.add(key)
                return true
            }
        })
        .sort((a, b) => a.timestamp - b.timestamp)
}

const generateRecordingReportDurations = (cache: Record<string, any>): RecordingReportLoadTimes => {
    return {
        metadata: cache.metadataLoadDuration || Math.round(performance.now() - cache.metaStartTime),
        snapshots: cache.snapshotsLoadDuration || Math.round(performance.now() - cache.snapshotsStartTime),
        events: cache.eventsLoadDuration || Math.round(performance.now() - cache.eventsStartTime),
        firstPaint: cache.firstPaintDuration,
    }
}

const resetTimingsCache = (cache: Record<string, any>): void => {
    cache.metaStartTime = null
    cache.metadataLoadDuration = null
    cache.snapshotsStartTime = null
    cache.snapshotsLoadDuration = null
    cache.eventsStartTime = null
    cache.eventsLoadDuration = null
    cache.firstPaintDuration = null
}

export interface SessionRecordingDataLogicProps {
    sessionRecordingId: SessionRecordingId
    realTimePollingIntervalMilliseconds?: number
}

function makeEventsQuery(
    person: PersonType | null,
    distinctId: string | null,
    start: Dayjs,
    end: Dayjs,
    properties: AnyPropertyFilter[]
): Promise<unknown> {
    return api.query({
        kind: NodeKind.EventsQuery,
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
        personId: person ? String(person.id) : undefined,
        after: start.subtract(BUFFER_MS, 'ms').format(),
        before: end.add(BUFFER_MS, 'ms').format(),
        properties: properties,
        where: distinctId ? [`distinct_id = ('${distinctId}')`] : undefined,
    })
}

async function processEncodedResponse(
    encodedResponse: (EncodedRecordingSnapshot | string)[],
    props: SessionRecordingDataLogicProps,
    existingData: SessionPlayerSnapshotData | null,
    featureFlags: FeatureFlagsSet
): Promise<{ transformed: RecordingSnapshot[]; untransformed: RecordingSnapshot[] | null }> {
    let untransformed: RecordingSnapshot[] | null = null

    const transformed = prepareRecordingSnapshots(
        await parseEncodedSnapshots(
            encodedResponse,
            props.sessionRecordingId,
            !!featureFlags[FEATURE_FLAGS.SESSION_REPLAY_MOBILE]
        ),
        existingData?.snapshots ?? []
    )

    if (featureFlags[FEATURE_FLAGS.SESSION_REPLAY_EXPORT_MOBILE_DATA]) {
        untransformed = prepareRecordingSnapshots(
            await parseEncodedSnapshots(
                encodedResponse,
                props.sessionRecordingId,
                false // don't transform mobile data
            ),
            existingData?.untransformed_snapshots ?? []
        )
    }

    return { transformed, untransformed }
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect({
        logic: [eventUsageLogic],
        values: [featureFlagLogic, ['featureFlags']],
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
        startRealTimePolling: true,
        pollRecordingSnapshots: true,
        pollingLoadedNoNewData: true,
    }),
    reducers(() => ({
        unnecessaryPollingCount: [
            0,
            {
                pollingLoadedNoNewData: (state) => state + 1,
            },
        ],
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
    listeners(({ values, actions, cache, props }) => ({
        pollRecordingSnapshotsSuccess: () => {
            // always make sure we've cleared up the last timeout
            clearTimeout(cache.realTimePollingTimeoutID)
            cache.realTimePollingTimeoutID = null

            // ten is an arbitrary limit to try to avoid sending requests to our backend unnecessarily
            // we could change this or add to it e.g. only poll if browser is visible to user
            if (values.unnecessaryPollingCount <= 10) {
                cache.realTimePollingTimeoutID = setTimeout(() => {
                    actions.pollRecordingSnapshots()
                }, props.realTimePollingIntervalMilliseconds || DEFAULT_REALTIME_POLLING_MILLIS)
            }
        },
        startRealTimePolling: () => {
            if (cache.realTimePollingTimeoutID) {
                clearTimeout(cache.realTimePollingTimeoutID)
            }

            cache.realTimePollingTimeoutID = setTimeout(() => {
                actions.pollRecordingSnapshots()
            }, props.realTimePollingIntervalMilliseconds || DEFAULT_REALTIME_POLLING_MILLIS)
        },
        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
        },
        loadRecordingSnapshots: () => {
            actions.loadEvents()
        },
        loadRecordingMetaSuccess: () => {
            cache.metadataLoadDuration = Math.round(performance.now() - cache.metaStartTime)
            actions.reportUsageIfFullyLoaded()
        },
        loadRecordingMetaFailure: () => {
            cache.metadataLoadDuration = Math.round(performance.now() - cache.metaStartTime)
        },
        loadRecordingSnapshotsSuccess: () => {
            const { snapshots, sources } = values.sessionPlayerSnapshotData ?? {}
            if (snapshots) {
                if (!snapshots.length && sources?.length === 1) {
                    // We got only a single source to load, loaded it successfully, but it had no snapshots.
                    posthog.capture('recording_snapshots_v2_empty_response', {
                        source: sources[0],
                    })

                    // If we only have a realtime source and its empty, start polling it anyway
                    if (sources[0].source === SnapshotSourceType.realtime) {
                        actions.startRealTimePolling()
                    }

                    return
                }

                if (!cache.firstPaintDuration) {
                    cache.firstPaintDuration = Math.round(performance.now() - cache.snapshotsStartTime)
                    actions.reportViewed()
                }
            }

            const nextSourceToLoad = sources?.find((s) => !s.loaded)

            if (nextSourceToLoad) {
                actions.loadRecordingSnapshots(nextSourceToLoad)
            } else {
                cache.snapshotsLoadDuration = Math.round(performance.now() - cache.snapshotsStartTime)
                actions.reportUsageIfFullyLoaded()

                // If we have a realtime source, start polling it
                const realTimeSource = sources?.find((s) => s.source === SnapshotSourceType.realtime)
                if (realTimeSource) {
                    actions.startRealTimePolling()
                }
            }
        },
        loadRecordingSnapshotsFailure: () => {
            cache.snapshotsLoadDuration = Math.round(performance.now() - cache.snapshotsStartTime)
        },
        loadEventsSuccess: () => {
            cache.eventsLoadDuration = Math.round(performance.now() - cache.eventsStartTime)
            actions.reportUsageIfFullyLoaded()
        },
        loadEventsFailure: () => {
            cache.eventsLoadDuration = Math.round(performance.now() - cache.eventsStartTime)
        },
        reportUsageIfFullyLoaded: (_, breakpoint) => {
            breakpoint()
            if (values.fullyLoaded) {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    generateRecordingReportDurations(cache),
                    SessionRecordingUsageType.LOADED,
                    0
                )
                // Reset cache now that final usage report has been sent
                resetTimingsCache(cache)
            }
        },
        reportViewed: async (_, breakpoint) => {
            const durations = generateRecordingReportDurations(cache)
            breakpoint()
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
    loaders(({ values, props, cache, actions }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                if (!props.sessionRecordingId) {
                    return null
                }

                cache.metaStartTime = performance.now()

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
                await breakpoint(100)
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
                pollRecordingSnapshots: async (_, breakpoint: BreakPointFunction) => {
                    await breakpoint(1) // debounce
                    const response = await api.recordings.listSnapshots(
                        props.sessionRecordingId,
                        REALTIME_POLLING_PARAMS
                    )
                    breakpoint() // handle out of order

                    if (response.snapshots) {
                        const { transformed, untransformed } = await processEncodedResponse(
                            response.snapshots,
                            props,
                            values.sessionPlayerSnapshotData,
                            values.featureFlags
                        )

                        if (transformed.length === (values.sessionPlayerSnapshotData?.snapshots || []).length) {
                            actions.pollingLoadedNoNewData()
                        }

                        return {
                            ...(values.sessionPlayerSnapshotData || {}),
                            snapshots: transformed,
                            untransformed_snapshots: untransformed ?? undefined,
                        }
                    }
                    return values.sessionPlayerSnapshotData
                },
                loadRecordingSnapshots: async ({ source }, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    if (!props.sessionRecordingId) {
                        return values.sessionPlayerSnapshotData
                    }

                    const snapshotLoadingStartTime = performance.now()

                    if (!cache.snapshotsStartTime) {
                        cache.snapshotsStartTime = snapshotLoadingStartTime
                    }

                    const data: SessionPlayerSnapshotData = {
                        ...(values.sessionPlayerSnapshotData || {}),
                    }

                    await breakpoint(1)

                    if (source?.source === SnapshotSourceType.blob) {
                        if (!source.blob_key) {
                            throw new Error('Missing key')
                        }
                        const encodedResponse = await api.recordings.getBlobSnapshots(
                            props.sessionRecordingId,
                            source.blob_key
                        )

                        const { transformed, untransformed } = await processEncodedResponse(
                            encodedResponse,
                            props,
                            values.sessionPlayerSnapshotData,
                            values.featureFlags
                        )
                        data.snapshots = transformed
                        data.untransformed_snapshots = untransformed ?? undefined
                    } else {
                        const params = toParams({
                            source: source?.source,
                            key: source?.blob_key,
                            version: '2',
                        })
                        const response = await api.recordings.listSnapshots(props.sessionRecordingId, params)
                        if (response.snapshots) {
                            const { transformed, untransformed } = await processEncodedResponse(
                                response.snapshots,
                                props,
                                values.sessionPlayerSnapshotData,
                                values.featureFlags
                            )
                            data.snapshots = transformed
                            data.untransformed_snapshots = untransformed ?? undefined
                        }

                        if (response.sources) {
                            data.sources = response.sources
                        }
                    }

                    if (source) {
                        source.loaded = true

                        posthog.capture('recording_snapshot_loaded', {
                            source: source.source,
                            duration: Math.round(performance.now() - snapshotLoadingStartTime),
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
                    if (!cache.eventsStartTime) {
                        cache.eventsStartTime = performance.now()
                    }

                    const { start, end, person } = values.sessionPlayerData

                    if (!person || !start || !end) {
                        return null
                    }

                    const [sessionEvents, relatedEvents]: any[] = await Promise.all([
                        // make one query for all events that are part of the session
                        makeEventsQuery(null, null, start, end, [
                            {
                                key: '$session_id',
                                value: [props.sessionRecordingId],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ]),
                        // make a second for all events from that person,
                        // not marked as part of the session
                        // but in the same time range
                        // these are probably e.g. backend events for the session
                        // but with no session id
                        // since posthog-js must always add session id we can also
                        // take advantage of lib being materialized and further filter
                        makeEventsQuery(null, values.sessionPlayerMetaData?.distinct_id || null, start, end, [
                            {
                                key: '$session_id',
                                value: '',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                            {
                                key: '$lib',
                                value: ['web'],
                                operator: PropertyOperator.IsNot,
                                type: PropertyFilterType.Event,
                            },
                        ]),
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
        similarRecordings: [
            null as [string, number][] | null,
            {
                fetchSimilarRecordings: async () => {
                    return await api.recordings.similarRecordings(props.sessionRecordingId)
                },
            },
        ],
    })),
    selectors({
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

        snapshotsInvalid: [
            (s, p) => [s.snapshotsByWindowId, s.fullyLoaded, p.sessionRecordingId],
            (snapshotsByWindowId, fullyLoaded, sessionRecordingId): boolean => {
                if (!fullyLoaded) {
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
                        ...windowsHaveFullSnapshot,
                        sessionId: sessionRecordingId,
                    })
                } else if (anyWindowMissingFullSnapshot) {
                    posthog.capture('recording_window_missing_full_snapshot', {
                        ...windowsHaveFullSnapshot,
                        sessionId: sessionRecordingId,
                    })
                }

                return everyWindowMissingFullSnapshot
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
    afterMount(({ cache }) => {
        resetTimingsCache(cache)
    }),
    beforeUnmount(({ cache }) => {
        resetTimingsCache(cache)
    }),
])
