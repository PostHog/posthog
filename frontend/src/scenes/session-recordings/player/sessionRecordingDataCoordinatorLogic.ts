import equal from 'fast-deep-equal'
import { actions, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import { EventType, customEvent, eventWithTime } from 'posthog-js/rrweb-types'

import {
    getHrefFromSnapshot,
    keyForSource,
    processAllSnapshots,
    SnapshotStore,
    SourceLoadingState,
} from '@posthog/replay-shared'

import { Dayjs, dayjs, now } from 'lib/dayjs'

import {
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionRecordingId,
    SessionRecordingType,
    TeamPublicType,
    TeamType,
} from '~/types'

import { ExportedSessionRecordingFileV2 } from '../file-playback/types'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { sessionEventsDataLogic } from './sessionEventsDataLogic'
import { sessionRecordingCommentsLogic } from './sessionRecordingCommentsLogic'
import type { sessionRecordingDataCoordinatorLogicType } from './sessionRecordingDataCoordinatorLogicType'
import { sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'
import { posthogTelemetry } from './snapshot-processing/process-all-snapshots'
import { snapshotDataLogic } from './snapshotDataLogic'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

export interface SessionRecordingDataCoordinatorLogicProps {
    sessionRecordingId: SessionRecordingId
    // allows disabling polling for new sources in tests
    blobV2PollingDisabled?: boolean
    playerKey?: string
    accessToken?: string
}

// For a short window after a recording starts it may still be ingesting, so a missing full
// snapshot is not yet definitive — late data (including the initial full snapshot) can still
// arrive. Past this grace period a missing full snapshot means the data never reached PostHog.
// NB: this clock is anchored on recording start, whereas snapshotDataLogic's
// POLLING_INACTIVITY_TIMEOUT_MS is anchored on the last source change — they both happen to be
// ~5 minutes but measure from different events, so tune them together, not in isolation.
export const INGESTION_GRACE_PERIOD_MINUTES = 5

export function isWithinIngestionGracePeriod(start: Dayjs | null): boolean {
    return start != null && now().diff(start, 'minute') <= INGESTION_GRACE_PERIOD_MINUTES
}

export const sessionRecordingDataCoordinatorLogic = kea<sessionRecordingDataCoordinatorLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataCoordinatorLogic', key]),
    props({} as SessionRecordingDataCoordinatorLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect(({ sessionRecordingId, blobV2PollingDisabled, accessToken }: SessionRecordingDataCoordinatorLogicProps) => {
        const metaLogic = sessionRecordingMetaLogic({
            sessionRecordingId,
            blobV2PollingDisabled,
            accessToken,
        })
        const eventsLogic = sessionEventsDataLogic({
            sessionRecordingId,
            blobV2PollingDisabled,
            accessToken,
        })
        const commentsLogic = sessionRecordingCommentsLogic({
            sessionRecordingId,
        })
        const snapLogic = snapshotDataLogic({
            sessionRecordingId,
            blobV2PollingDisabled,
            accessToken,
        })
        return {
            actions: [
                sessionRecordingEventUsageLogic,
                ['reportRecordingLoaded'],
                metaLogic,
                [
                    'loadRecordingMeta',
                    'loadRecordingMetaSuccess',
                    'loadRecordingMetaFailure',
                    'maybeLoadRecordingMeta',
                    'setTrackedWindow',
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadSnapshotsForSourceSuccess',
                    'setSnapshots',
                    'loadRecordingFromFile',
                    'registerWindowId',
                ],
                eventsLogic,
                ['loadEvents', 'loadFullEventData', 'loadEventsSuccess', 'loadFullEventDataSuccess'],
                commentsLogic,
                [
                    'loadRecordingComments',
                    'loadRecordingNotebookComments',
                    'loadRecordingCommentsSuccess',
                    'loadRecordingNotebookCommentsSuccess',
                ],
                snapLogic,
                ['storeUpdated'],
            ],
            values: [
                metaLogic,
                [
                    'sessionPlayerMetaData',
                    'sessionPlayerMetaDataLoading',
                    'isNotFound',
                    'loadMetaError',
                    'trackedWindow',
                    'snapshotSources',
                    'snapshotsLoading',
                    'snapshotsLoaded',
                    'currentTeam',
                    'annotations',
                    'annotationsLoading',
                    'isLoadingSnapshots',
                    'uuidToIndex',
                    'getWindowId',
                    'isRecordingDeleted',
                    'recordingDeletedAt',
                    'recordingDeletedBy',
                ],
                eventsLogic,
                [
                    'sessionEventsData',
                    'sessionEventsDataLoading',
                    'webVitalsEvents',
                    'AIEvents',
                    'viewportForTimestamp',
                ],
                commentsLogic,
                [
                    'sessionComments',
                    'sessionCommentsLoading',
                    'sessionNotebookComments',
                    'sessionNotebookCommentsLoading',
                ],
                snapLogic,
                ['snapshotStore', 'storeVersion', 'sourceLoadingStates'],
            ],
        }
    }),
    actions({
        loadRecordingData: true,
        reportUsageIfFullyLoaded: true,
        setRecordingReportedLoaded: true,
        processSnapshotsAsync: true,
        setProcessedSnapshots: (snapshots: RecordingSnapshot[]) => ({ snapshots }),
        // Terminal: snapshot processing kept throwing and all retries are exhausted. The player maps
        // this to an error state — without it the affected sources stay unpromoted forever and the
        // player buffers with no error surfaced.
        snapshotProcessingFailed: true,
    }),
    reducers(() => ({
        reportedLoaded: [
            false,
            {
                setRecordingReportedLoaded: () => true,
            },
        ],
        processedSnapshots: [
            [] as RecordingSnapshot[],
            {
                setProcessedSnapshots: (_, { snapshots }) => snapshots,
            },
        ],
    })),
    listeners(({ values, actions, props, cache }) => ({
        loadRecordingData: () => {
            actions.loadRecordingMeta()
        },

        loadRecordingMetaSuccess: () => {
            if (props.sessionRecordingId) {
                actions.loadSnapshotSources()
            }
            actions.reportUsageIfFullyLoaded()
        },

        loadNextSnapshotSource: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
            // Events carry the viewport data used to patch missing meta events. Sources processed
            // before events loaded were left uncached (viewportGaps) — re-run so they get their meta.
            if (cache.processingCache?.viewportGaps?.size) {
                actions.processSnapshotsAsync()
            }
        },

        // loadFullEventData shares the sessionEventsData loader, so while it is in flight
        // fullyLoaded is false — re-check once it settles or the loaded report can be skipped
        loadFullEventDataSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadSnapshotsForSourceSuccess: () => {
            actions.reportUsageIfFullyLoaded()
            actions.processSnapshotsAsync()
        },

        loadRecordingCommentsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadRecordingNotebookCommentsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        setProcessedSnapshots: () => {
            actions.reportUsageIfFullyLoaded()
        },

        processSnapshotsAsync: async (_, breakpoint) => {
            cache.processingCache = cache.processingCache || { snapshots: {} }

            const sources = values.snapshotSources
            const snapshotsBySource = {} as Record<string, { snapshots: RecordingSnapshot[] }>
            // fetched sources this pass will cover — promoted to loaded on completion, including empty
            // ones that contribute no snapshots. Tracked by key, not index: a setSources refresh during
            // the await below re-indexes entries, and promoting stale indexes would flip the wrong source.
            const coveredKeys: string[] = []
            if (sources) {
                for (let i = 0; i < sources.length; i++) {
                    const entry = values.snapshotStore.getEntry(i)
                    if (entry?.state === 'fetched') {
                        coveredKeys.push(keyForSource(sources[i]))
                    }
                    if (entry?.state !== 'unloaded' && entry?.processedSnapshots?.length) {
                        snapshotsBySource[keyForSource(sources[i])] = {
                            snapshots: entry.processedSnapshots,
                        }
                    }
                }
            }

            let result: RecordingSnapshot[]
            try {
                result = await processAllSnapshots(
                    sources,
                    snapshotsBySource,
                    cache.processingCache,
                    values.viewportForTimestamp,
                    props.sessionRecordingId,
                    posthogTelemetry
                )
            } catch (error) {
                // A processing throw on the final batch would otherwise leave fetched sources unplayable forever (nothing re-triggers processing), so retry with backoff.
                posthog.captureException(error)
                cache.processingFailureCount = (cache.processingFailureCount ?? 0) + 1
                if (cache.processingFailureCount <= 3) {
                    await breakpoint(cache.processingFailureCount * 1000)
                    actions.processSnapshotsAsync()
                } else {
                    // Give up loudly: nothing re-triggers processing from here, so surface a terminal
                    // error instead of leaving the player buffering forever.
                    actions.snapshotProcessingFailed()
                }
                return
            }
            cache.processingFailureCount = 0

            breakpoint()

            const keyToIndex = new Map((values.snapshotSources ?? []).map((s, i) => [keyForSource(s), i]))
            const coveredIndexes = coveredKeys.map((k) => keyToIndex.get(k)).filter((i): i is number => i !== undefined)

            // Promotion is what makes these sources count as playable — the oracle, segments, and planner all key on it, so it must land with the processed snapshots.
            const promoted = values.snapshotStore.markProcessed(coveredIndexes)
            // processAllSnapshots may synthesize full snapshots (e.g. for mobile recordings).
            // Sync them back to the store so canPlayAt() and the load planner work correctly.
            const synced = values.snapshotStore.syncFullSnapshotTimestamps(result)

            // Release raw snapshot arrays from the store — only the metadata (fullSnapshots, state) is
            // still needed. Sources processed without viewport data keep their raw snapshots so the
            // loadEventsSuccess re-run below can re-process them with a viewport.
            const viewportGapIndexes = new Set(
                [...(cache.processingCache.viewportGaps ?? [])]
                    .map((k) => keyToIndex.get(k))
                    .filter((i): i is number => i !== undefined)
            )
            values.snapshotStore.clearSnapshotData(viewportGapIndexes)

            if (promoted || synced) {
                actions.storeUpdated()
            }
            actions.setProcessedSnapshots(result)
        },

        reportUsageIfFullyLoaded: (_, breakpoint) => {
            breakpoint()
            if (values.fullyLoaded && !values.reportedLoaded) {
                actions.setRecordingReportedLoaded()
                actions.reportRecordingLoaded(values.sessionPlayerData, values.sessionPlayerMetaData)
            }
        },
    })),
    selectors(() => ({
        snapshots: [
            (s) => [s.processedSnapshots],
            (processedSnapshots: RecordingSnapshot[]): RecordingSnapshot[] => {
                return processedSnapshots
            },
        ],

        start: [
            (s) => [s.snapshots, s.sessionPlayerMetaData],
            (snapshots, meta): Dayjs | null => {
                const firstSnapshot = snapshots[0] || null
                const eventStart = meta?.start_time ? dayjs(meta.start_time) : null
                const snapshotStart = firstSnapshot ? dayjs(firstSnapshot.timestamp) : null

                if (eventStart && snapshotStart) {
                    return eventStart.isBefore(snapshotStart) ? eventStart : snapshotStart
                }
                return eventStart || snapshotStart
            },
        ],

        end: [
            (s) => [s.snapshots, s.sessionPlayerMetaData],
            (snapshots, meta): Dayjs | null => {
                const lastSnapshot = snapshots[snapshots.length - 1] || null
                const eventEnd = meta?.end_time ? dayjs(meta.end_time) : null
                const snapshotEnd = lastSnapshot ? dayjs(lastSnapshot.timestamp) : null

                if (eventEnd && snapshotEnd) {
                    return eventEnd.isAfter(snapshotEnd) ? eventEnd : snapshotEnd
                }
                return eventEnd || snapshotEnd
            },
        ],

        durationMs: [
            (s) => [s.start, s.end, s.sessionPlayerMetaData, s.fullyLoaded],
            (start, end, meta: SessionRecordingType | null, fullyLoaded: boolean): number => {
                if (!start || !end) {
                    return 0
                }
                const snapshotDuration = end.diff(start)
                if (fullyLoaded && meta?.recording_duration) {
                    return Math.min(snapshotDuration, meta.recording_duration * 1000)
                }
                return snapshotDuration
            },
        ],

        segments: [
            (s) => [
                s.snapshots,
                s.start,
                s.end,
                s.trackedWindow,
                s.snapshotsByWindowId,
                s.snapshotStore,
                s.storeVersion,
            ],
            (
                snapshots: RecordingSnapshot[],
                start: Dayjs | null,
                end: Dayjs | null,
                trackedWindow: number | null,
                snapshotsByWindowId: Record<number, eventWithTime[]>,
                snapshotStore: SnapshotStore
            ): RecordingSegment[] => {
                return createSegments(snapshots || [], start, end, trackedWindow, snapshotsByWindowId, (s, e) =>
                    snapshotStore.isRangeLoaded(s, e)
                )
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.snapshots],
            (snapshots: RecordingSnapshot[]): Record<number, eventWithTime[]> => {
                return mapSnapshotsToWindowId(snapshots || [])
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

        windowIdForTimestamp: [
            (s) => [s.segments],
            (segments) => {
                // memoized per segments recompute — segments reshape as data loads, so a logic-lifetime cache would pin stale window attributions
                const memo: Record<number, number | undefined> = {}
                return (timestamp: number): number | undefined => {
                    if (timestamp in memo) {
                        return memo[timestamp]
                    }
                    const matchingWindowId = segments.find(
                        (segment) => segment.startTimestamp <= timestamp && segment.endTimestamp >= timestamp
                    )?.windowId

                    memo[timestamp] = matchingWindowId
                    return matchingWindowId
                }
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

        windowsHaveFullSnapshot: [
            (s) => [s.snapshotsByWindowId],
            (snapshotsByWindowId: Record<number, eventWithTime[]>) => {
                return Object.entries(snapshotsByWindowId).reduce(
                    (acc, [windowId, events]) => {
                        acc[`window-id-${windowId}-has-full-snapshot`] = events.some(
                            (event) => event.type === EventType.FullSnapshot
                        )
                        return acc
                    },
                    {} as Record<string, boolean>
                )
            },
            {
                resultEqualityCheck: equal,
            },
        ],

        snapshotsInvalid: [
            (s, p) => [s.windowsHaveFullSnapshot, s.fullyLoaded, s.start, p.sessionRecordingId, s.currentTeam],
            (
                windowsHaveFullSnapshot: Record<string, boolean>,
                fullyLoaded: boolean,
                start: Dayjs | null,
                sessionRecordingId: SessionRecordingId,
                currentTeam: TeamPublicType | TeamType | null
            ): boolean => {
                if (!fullyLoaded || !start) {
                    return false
                }

                const noWindowHasFullSnapshot = !Object.values(windowsHaveFullSnapshot).some((x) => x)
                const someWindowMissingFullSnapshot = !Object.values(windowsHaveFullSnapshot).every((x) => x)

                const recordingAgeMs = now().diff(start, 'millisecond')

                if (noWindowHasFullSnapshot) {
                    // video is definitely unplayable
                    posthog.capture('recording_has_no_full_snapshot', {
                        watchedSession: sessionRecordingId,
                        teamId: currentTeam?.id,
                        teamName: currentTeam?.name,
                        recordingAgeMs,
                    })
                } else if (someWindowMissingFullSnapshot) {
                    posthog.capture('recording_window_missing_full_snapshot', {
                        watchedSession: sessionRecordingId,
                        teamID: currentTeam?.id,
                        teamName: currentTeam?.name,
                        recordingAgeMs,
                    })
                }

                return noWindowHasFullSnapshot
            },
        ],

        isRecentAndInvalid: [
            (s) => [s.start, s.snapshotsInvalid],
            (start, snapshotsInvalid) => {
                return snapshotsInvalid && isWithinIngestionGracePeriod(start)
            },
        ],

        // past the ingestion grace period, a missing full snapshot means the data never arrived,
        // e.g. the browser closed or went offline before the recording finished uploading
        isOldAndInvalid: [
            (s) => [s.snapshotsInvalid, s.isRecentAndInvalid],
            (snapshotsInvalid, isRecentAndInvalid) => snapshotsInvalid && !isRecentAndInvalid,
        ],

        windowIds: [
            (s) => [s.snapshotsByWindowId],
            (snapshotsByWindowId: Record<number, eventWithTime[]>): number[] => {
                return Object.keys(snapshotsByWindowId).map(Number)
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

        effectiveSourceLoadingStates: [
            (s) => [s.sourceLoadingStates, s.segments],
            (states: SourceLoadingState[], segments: RecordingSegment[]): SourceLoadingState[] => {
                let lastNonGapState: SourceLoadingState['state'] = 'unloaded'
                return states.map((s) => {
                    const inGap = !segments.some(
                        (seg) => seg.kind !== 'gap' && seg.startTimestamp < s.endMs && seg.endTimestamp > s.startMs
                    )
                    if (inGap) {
                        return { ...s, state: lastNonGapState }
                    }
                    lastNonGapState = s.state
                    return s
                })
            },
        ],

        fullyLoaded: [
            (s) => [
                s.snapshots,
                s.segments,
                s.sessionPlayerMetaDataLoading,
                s.snapshotsLoading,
                s.sessionEventsDataLoading,
                s.sessionCommentsLoading,
                s.sessionNotebookCommentsLoading,
            ],
            (
                snapshots,
                segments,
                sessionPlayerMetaDataLoading,
                snapshotsLoading,
                sessionEventsDataLoading,
                sessionCommentsLoading,
                sessionNotebookCommentsLoading
            ): boolean => {
                // Check if there's a buffer segment (unloaded data)
                const hasBufferSegment = segments.some((segment) => segment.kind === 'buffer')

                return (
                    !!snapshots?.length &&
                    !sessionPlayerMetaDataLoading &&
                    !snapshotsLoading &&
                    !sessionEventsDataLoading &&
                    !sessionCommentsLoading &&
                    !sessionNotebookCommentsLoading &&
                    !hasBufferSegment
                )
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
                meta: SessionRecordingType | null,
                snapshotsByWindowId: Record<number, eventWithTime[]>,
                segments: RecordingSegment[],
                bufferedToTime: number | null,
                start: Dayjs | null,
                end: Dayjs | null,
                durationMs: number,
                fullyLoaded: boolean,
                sessionRecordingId: SessionRecordingId
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
    })),
    beforeUnmount(({ cache, actions, values }) => {
        cache.processingCache = undefined
        // Force clear processedSnapshots to release memory immediately
        // This breaks the reference chain in selector memoization cache
        if (actions) {
            actions.setProcessedSnapshots([])
            // Force selectors to recompute with empty snapshots by reading them
            // This updates the reselect cache with empty values instead of leaving old data cached
            void values.snapshotsByWindowId
            void values.sessionPlayerData
        }
    }),
    subscriptions(({ values }) => ({
        isRecentAndInvalid: (prev: boolean, next: boolean) => {
            if (!prev && next) {
                posthog.capture('recording cannot playback yet', {
                    watchedSession: values.sessionPlayerData.sessionRecordingId,
                })
            }
        },
    })),
])
