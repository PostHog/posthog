import { actions, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { EventType, customEvent, eventWithTime } from '@posthog/rrweb-types'

import { Dayjs, dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils'

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
import { getHrefFromSnapshot } from './snapshot-processing/patch-meta-event'
import { ProcessingCache, processAllSnapshots } from './snapshot-processing/process-all-snapshots'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'

export interface SessionRecordingDataCoordinatorLogicProps {
    sessionRecordingId: SessionRecordingId
    // allows disabling polling for new sources in tests
    blobV2PollingDisabled?: boolean
    playerKey?: string
    accessToken?: string
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
                    'persistRecording',
                    'maybePersistRecording',
                    'setTrackedWindow',
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadSnapshotsForSourceSuccess',
                    'setSnapshots',
                    'loadRecordingFromFile',
                ],
                eventsLogic,
                ['loadEvents', 'loadFullEventData', 'loadEventsSuccess'],
                commentsLogic,
                [
                    'loadRecordingComments',
                    'loadRecordingNotebookComments',
                    'loadRecordingCommentsSuccess',
                    'loadRecordingNotebookCommentsSuccess',
                ],
            ],
            values: [
                metaLogic,
                [
                    'sessionPlayerMetaData',
                    'sessionPlayerMetaDataLoading',
                    'isNotFound',
                    'trackedWindow',
                    'snapshotSources',
                    'snapshotsBySources',
                    'snapshotsLoading',
                    'snapshotsLoaded',
                    'currentTeam',
                    'annotations',
                    'annotationsLoading',
                    'isLoadingSnapshots',
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
            ],
        }
    }),
    actions({
        loadRecordingData: true,
        reportUsageIfFullyLoaded: true,
        setRecordingReportedLoaded: true,
    }),
    reducers(() => ({
        reportedLoaded: [
            false,
            {
                setRecordingReportedLoaded: () => true,
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        loadRecordingData: () => {
            actions.loadRecordingMeta()
        },

        loadRecordingMetaSuccess: () => {
            actions.loadSnapshotSources()
            actions.reportUsageIfFullyLoaded()
        },

        loadNextSnapshotSource: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadSnapshotsForSourceSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadRecordingCommentsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        loadRecordingNotebookCommentsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },

        reportUsageIfFullyLoaded: (_, breakpoint) => {
            breakpoint()
            if (values.fullyLoaded && !values.reportedLoaded) {
                actions.setRecordingReportedLoaded()
                actions.reportRecordingLoaded(values.sessionPlayerData, values.sessionPlayerMetaData)
            }
        },
    })),
    selectors(({ cache }) => ({
        snapshots: [
            (s, p) => [s.snapshotSources, s.viewportForTimestamp, p.sessionRecordingId, s.snapshotsBySources],
            (sources, viewportForTimestamp, sessionRecordingId, snapshotsBySources): RecordingSnapshot[] => {
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
            (s) => [s.start, s.end],
            (start, end): number => {
                return !!start && !!end ? end.diff(start) : 0
            },
        ],

        segments: [
            (s) => [s.snapshots, s.start, s.end, s.trackedWindow, s.snapshotsByWindowId, s.isLoadingSnapshots],
            (
                snapshots: RecordingSnapshot[],
                start: Dayjs | null,
                end: Dayjs | null,
                trackedWindow: string | null,
                snapshotsByWindowId: Record<string, eventWithTime[]>,
                isLoadingSnapshots: boolean
            ): RecordingSegment[] => {
                const segments = createSegments(snapshots || [], start, end, trackedWindow, snapshotsByWindowId)

                return segments.map((segment) => {
                    if (segment.kind === 'buffer') {
                        return {
                            ...segment,
                            isLoading: isLoadingSnapshots,
                        }
                    }
                    return segment
                })
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.snapshots],
            (snapshots) => {
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
            (snapshotsByWindowId: Record<string, eventWithTime[]>) => {
                return Object.entries(snapshotsByWindowId).reduce((acc, [windowId, events]) => {
                    acc[`window-id-${windowId}-has-full-snapshot`] = events.some(
                        (event) => event.type === EventType.FullSnapshot
                    )
                    return acc
                }, {})
            },
            {
                resultEqualityCheck: objectsEqual,
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

        windowIds: [
            (s) => [s.snapshotsByWindowId],
            (snapshotsByWindowId: Record<string, eventWithTime[]>): string[] => {
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
                snapshotsByWindowId: Record<string, eventWithTime[]>,
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
    beforeUnmount(({ cache }) => {
        cache.windowIdForTimestamp = undefined
        cache.processingCache = undefined
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
