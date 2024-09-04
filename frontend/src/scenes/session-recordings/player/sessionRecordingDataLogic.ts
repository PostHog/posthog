import posthogEE from '@posthog/ee/exports'
import { customEvent, EventType, eventWithTime } from '@rrweb/types'
import { captureException } from '@sentry/react'
import {
    actions,
    afterMount,
    beforeUnmount,
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
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
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
    SessionRecordingId,
    SessionRecordingSnapshotParams,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
    SessionRecordingType,
    SessionRecordingUsageType,
    SnapshotSourceType,
} from '~/types'

import { PostHogEE } from '../../../../@posthog/ee/types'
import { ExportedSessionRecordingFileV2 } from '../file-playback/types'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.
const DEFAULT_REALTIME_POLLING_MILLIS = 3000

let postHogEEModule: PostHogEE

function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[],
    sessionId: string,
    // this is only kept so that we can export the untransformed data for debugging
    withMobileTransformer: boolean = true
): Promise<RecordingSnapshot[]> => {
    if (!postHogEEModule) {
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

/*
    cyrb53 (c) 2018 bryc (github.com/bryc)
    License: Public domain. Attribution appreciated.
    A fast and simple 53-bit string hash function with decent collision resistance.
    Largely inspired by MurmurHash2/3, but with a focus on speed/simplicity.
*/
const cyrb53 = function (str: string, seed = 0): number {
    let h1 = 0xdeadbeef ^ seed,
        h2 = 0x41c6ce57 ^ seed
    for (let i = 0, ch; i < str.length; i++) {
        ch = str.charCodeAt(i)
        h1 = Math.imul(h1 ^ ch, 2654435761)
        h2 = Math.imul(h2 ^ ch, 1597334677)
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507)
    h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909)
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507)
    h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + (h1 >>> 0)
}

export const deduplicateSnapshots = (snapshots: RecordingSnapshot[] | null): RecordingSnapshot[] => {
    const seenHashes: Set<string> = new Set()

    return (snapshots ?? [])
        .filter((snapshot) => {
            // For a multitude of reasons, there can be duplicate snapshots in the same recording.
            // we have to stringify the snapshot to compare it to other snapshots.
            // so we can filter by storing them all in a set

            // we can see duplicates that only differ by delay - these still count as duplicates
            // even though the delay would hide that
            const { delay: _delay, ...delayFreeSnapshot } = snapshot
            // we check each item multiple times as new snapshots come in
            // so store the computer value on the object to save recalculating it so much
            const key = (snapshot as any).seen || cyrb53(JSON.stringify(delayFreeSnapshot))
            ;(snapshot as any).seen = key

            if (seenHashes.has(key)) {
                return false
            }
            seenHashes.add(key)
            return true
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
    featureFlags: FeatureFlagsSet
): Promise<{ transformed: RecordingSnapshot[]; untransformed: RecordingSnapshot[] | null }> {
    let untransformed: RecordingSnapshot[] | null = null

    const transformed = await parseEncodedSnapshots(encodedResponse, props.sessionRecordingId)

    if (featureFlags[FEATURE_FLAGS.SESSION_REPLAY_EXPORT_MOBILE_DATA]) {
        untransformed = await parseEncodedSnapshots(
            encodedResponse,
            props.sessionRecordingId,
            false // don't transform mobile data
        )
    }

    return { transformed, untransformed }
}

const getSourceKey = (source: SessionRecordingSnapshotSource): string => {
    // realtime sources vary so blob_key is not always present and is either null or undefined...
    // we only care about key when not realtime
    // and we'll always have a key when not realtime
    return `${source.source}-${source.blob_key || source.source}`
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
        loadSnapshots: true,
        loadSnapshotSources: true,
        loadNextSnapshotSource: true,
        loadSnapshotsForSource: (source: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'>) => ({ source }),
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType) => ({ event }),
        reportViewed: true,
        reportUsageIfFullyLoaded: true,
        persistRecording: true,
        maybePersistRecording: true,
        pollRealtimeSnapshots: true,
        stopRealtimePolling: true,
        setTrackedWindow: (windowId: string | null) => ({ windowId }),
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
        snapshotsBySource: [
            null as Record<string, SessionRecordingSnapshotSourceResponse> | null,
            {
                loadSnapshotsForSourceSuccess: (state, { snapshotsForSource }) => {
                    const sourceKey = getSourceKey(snapshotsForSource.source)

                    return {
                        ...state,
                        [sourceKey]: snapshotsForSource,
                    }
                },
            },
        ],
    })),
    loaders(({ values, props, cache }) => ({
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
        snapshotSources: [
            null as SessionRecordingSnapshotSource[] | null,
            {
                loadSnapshotSources: async () => {
                    const response = await api.recordings.listSnapshotSources(props.sessionRecordingId)
                    return response.sources ?? []
                },
            },
        ],
        snapshotsForSource: [
            null as SessionRecordingSnapshotSourceResponse | null,
            {
                loadSnapshotsForSource: async ({ source }, breakpoint) => {
                    let params: SessionRecordingSnapshotParams

                    if (source.source === SnapshotSourceType.blob) {
                        if (!source.blob_key) {
                            throw new Error('Missing key')
                        }
                        params = { blob_key: source.blob_key, source: 'blob' }
                    } else if (source.source === SnapshotSourceType.realtime) {
                        params = { source: 'realtime', version: '2024-04-30' }
                    } else {
                        throw new Error(`Unsupported source: ${source.source}`)
                    }

                    const snapshotLoadingStartTime = performance.now()

                    if (!cache.snapshotsStartTime) {
                        cache.snapshotsStartTime = snapshotLoadingStartTime
                    }

                    await breakpoint(1)

                    const response = await api.recordings.getSnapshots(props.sessionRecordingId, params).catch((e) => {
                        if (source.source === 'realtime' && e.status === 404) {
                            // Realtime source is not always available so a 404 is expected
                            return []
                        }
                        throw e
                    })

                    const { transformed, untransformed } = await processEncodedResponse(
                        response,
                        props,
                        values.featureFlags
                    )

                    return { snapshots: transformed, untransformed_snapshots: untransformed ?? undefined, source }
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

                    let loadedProperties: Record<string, any> = existingEvent.properties
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
                            loadedProperties = JSON.parse(result[0])
                            existingEvent.properties = loadedProperties
                            existingEvent.fullyLoaded = true
                        }
                    } catch (e) {
                        // NOTE: This is not ideal but should happen so rarely that it is tolerable.
                        existingEvent.fullyLoaded = true
                        captureException(e)
                    }

                    // here we map the events list because we want the result to be a new instance to trigger downstream recalculation
                    return !values.sessionEventsData
                        ? values.sessionEventsData
                        : values.sessionEventsData.map((x) => {
                              return x.id === event.id
                                  ? ({
                                        ...x,
                                        properties: loadedProperties,
                                        fullyLoaded: true,
                                    } as RecordingEventType)
                                  : x
                          })
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
        },
        loadSnapshotSources: () => {
            // We only load events once we actually start loading the recording
            actions.loadEvents()
        },
        loadRecordingMetaSuccess: () => {
            cache.metadataLoadDuration = Math.round(performance.now() - cache.metaStartTime)
            actions.reportUsageIfFullyLoaded()
        },
        loadRecordingMetaFailure: () => {
            cache.metadataLoadDuration = Math.round(performance.now() - cache.metaStartTime)
        },

        loadSnapshotSourcesSuccess: () => {
            // When we receive the list of sources we can kick off the loading chain
            actions.loadNextSnapshotSource()
        },

        loadSnapshotsForSourceSuccess: ({ snapshotsForSource }) => {
            const sources = values.snapshotSources
            const snapshots = snapshotsForSource.snapshots

            // Cache the last response count to detect if we're getting the same data over and over
            const newSnapshotsCount = snapshots.length

            if ((cache.lastSnapshotsCount ?? newSnapshotsCount) === newSnapshotsCount) {
                // if we're getting no results from realtime polling we can increment faster
                // so that we stop polling sooner
                const increment = newSnapshotsCount === 0 ? 2 : 1
                cache.lastSnapshotsUnchangedCount = (cache.lastSnapshotsUnchangedCount ?? 0) + increment
            } else {
                cache.lastSnapshotsUnchangedCount = 0
            }
            cache.lastSnapshotsCount = newSnapshotsCount

            if (!snapshots.length && sources?.length === 1) {
                // We got only a single source to load, loaded it successfully, but it had no snapshots.
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })
            } else if (!cache.firstPaintDuration) {
                cache.firstPaintDuration = Math.round(performance.now() - cache.snapshotsStartTime)
                actions.reportViewed()
            }

            actions.loadNextSnapshotSource()
        },

        loadNextSnapshotSource: () => {
            const nextSourceToLoad = values.snapshotSources?.find((s) => {
                const sourceKey = getSourceKey(s)
                return !values.snapshotsBySource?.[sourceKey]
            })

            if (nextSourceToLoad) {
                return actions.loadSnapshotsForSource(nextSourceToLoad)
            }

            // TODO: Move this to a one time check - only report once per recording
            cache.snapshotsLoadDuration = Math.round(performance.now() - cache.snapshotsStartTime)
            actions.reportUsageIfFullyLoaded()

            // If we have a realtime source, start polling it
            const realTimeSource = values.snapshotSources?.find((s) => s.source === SnapshotSourceType.realtime)
            if (realTimeSource) {
                actions.pollRealtimeSnapshots()
            }
        },
        loadSnapshotsForSourceFailure: () => {
            cache.snapshotsLoadDuration = Math.round(performance.now() - cache.snapshotsStartTime)
        },
        pollRealtimeSnapshots: () => {
            // always make sure we've cleared up the last timeout
            clearTimeout(cache.realTimePollingTimeoutID)
            cache.realTimePollingTimeoutID = null

            // ten is an arbitrary limit to try to avoid sending requests to our backend unnecessarily
            // we could change this or add to it e.g. only poll if browser is visible to user
            if ((cache.lastSnapshotsUnchangedCount ?? 0) <= 10) {
                cache.realTimePollingTimeoutID = setTimeout(() => {
                    actions.loadSnapshotsForSource({ source: SnapshotSourceType.realtime })
                }, props.realTimePollingIntervalMilliseconds || DEFAULT_REALTIME_POLLING_MILLIS)
            } else {
                actions.stopRealtimePolling()
            }
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
                    values.sessionPlayerMetaData,
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
                values.sessionPlayerMetaData,
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.ANALYZED,
                values.sessionPlayerMetaData,
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
    selectors(({ cache }) => ({
        webVitalsEvents: [
            (s) => [s.sessionEventsData],
            (sessionEventsData): RecordingEventType[] =>
                (sessionEventsData || []).filter((e) => e.event === '$web_vitals'),
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
            (s) => [s.snapshotSourcesLoading, s.snapshotsForSourceLoading],
            (snapshotSourcesLoading, snapshotsForSourceLoading): boolean => {
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
                    !!snapshots.length &&
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
            (s) => [s.snapshotSources, s.snapshotsBySource],
            (sources, snapshotsBySource): RecordingSnapshot[] => {
                const allSnapshots =
                    sources?.flatMap((source) => {
                        const sourceKey = getSourceKey(source)
                        return snapshotsBySource?.[sourceKey]?.snapshots || []
                    }) ?? []

                return deduplicateSnapshots(allSnapshots)
            },
        ],

        untransformedSnapshots: [
            (s) => [s.snapshotSources, s.snapshotsBySource],
            (sources, snapshotsBySource): RecordingSnapshot[] => {
                const allSnapshots =
                    sources?.flatMap((source) => {
                        const sourceKey = getSourceKey(source)
                        return snapshotsBySource?.[sourceKey]?.untransformed_snapshots || []
                    }) ?? []

                return deduplicateSnapshots(allSnapshots)
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.snapshots],
            (snapshots): Record<string, eventWithTime[]> => {
                return mapSnapshotsToWindowId(snapshots || [])
            },
        ],

        snapshotsInvalid: [
            (s, p) => [s.snapshotsByWindowId, s.fullyLoaded, s.start, p.sessionRecordingId],
            (snapshotsByWindowId, fullyLoaded, start, sessionRecordingId): boolean => {
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
                        sessionId: sessionRecordingId,
                    })
                } else if (anyWindowMissingFullSnapshot) {
                    posthog.capture('recording_window_missing_full_snapshot', {
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

        createExportJSON: [
            (s) => [s.sessionPlayerMetaData, s.snapshots, s.untransformedSnapshots],
            (
                sessionPlayerMetaData,
                snapshots,
                untransformedSnapshots
            ): ((exportUntransformedMobileSnapshotData: boolean) => ExportedSessionRecordingFileV2) => {
                return (exportUntransformedMobileSnapshotData: boolean) => ({
                    version: '2023-04-28',
                    data: {
                        id: sessionPlayerMetaData?.id ?? '',
                        person: sessionPlayerMetaData?.person,
                        snapshots: exportUntransformedMobileSnapshotData ? untransformedSnapshots : snapshots,
                    },
                })
            },
        ],

        customRRWebEvents: [
            (s) => [s.snapshots],
            (snapshots): customEvent[] => {
                return snapshots.filter((snapshot) => snapshot.type === EventType.Custom).map((x) => x as customEvent)
            },
        ],
    })),
    subscriptions(({ actions }) => ({
        webVitalsEvents: (value: RecordingEventType[]) => {
            value.forEach((item) => {
                // we preload all web vitals data, so it can be used before user interaction
                if (!item.fullyLoaded) {
                    actions.loadFullEventData(item)
                }
            })
        },
    })),
    afterMount(({ cache }) => {
        resetTimingsCache(cache)
    }),
    beforeUnmount(({ cache }) => {
        resetTimingsCache(cache)
    }),
])
