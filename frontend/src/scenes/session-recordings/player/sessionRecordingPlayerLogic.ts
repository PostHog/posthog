import {
    BuiltLogic,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { delay } from 'kea-test-utils'
import posthog from 'posthog-js'
import { RefObject } from 'react'

import { lemonToast } from '@posthog/lemon-ui'
import { ReplayPlugin, Replayer, playerConfig } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

import api from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { dayjs, now } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clamp, downloadFile, findLastIndex, objectsEqual, uuid } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { openBillingPopupModal } from 'scenes/billing/BillingPopup'
import { ReplayIframeData } from 'scenes/heatmaps/heatmapsBrowserLogic'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import {
    SessionRecordingDataCoordinatorLogicProps,
    sessionRecordingDataCoordinatorLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ExporterFormat, RecordingSegment, SessionPlayerData, SessionPlayerState } from '~/types'

import type { sessionRecordingsPlaylistLogicType } from '../playlist/sessionRecordingsPlaylistLogicType'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { getTestWorkerManager, terminateTestWorker } from './TestWorkerManager'
import { playerCommentOverlayLogic } from './commenting/playerFrameCommentOverlayLogic'
import { playerCommentOverlayLogicType } from './commenting/playerFrameCommentOverlayLogicType'
import { playerSettingsLogic } from './playerSettingsLogic'
import { BuiltLogging, COMMON_REPLAYER_CONFIG, CorsPlugin, HLSPlayerPlugin, makeLogger, makeNoOpLogger } from './rrweb'
import { AudioMuteReplayerPlugin } from './rrweb/audio/audio-mute-plugin'
import { CanvasReplayerPlugin } from './rrweb/canvas/canvas-plugin'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { DEFAULT_LOADING_BUFFER, snapshotDataLogic } from './snapshotDataLogic'
import { deleteRecording } from './utils/playerUtils'
import { SessionRecordingPlayerExplorerProps } from './view-explorer/SessionRecordingPlayerExplorer'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
export const PLAYBACK_SPEEDS = [0.5, 1, 1.5, 2, 3, 4, 8, 16]
export const ONE_FRAME_MS = 100 // We don't really have frames but this feels granular enough

export interface ResourceErrorDetails {
    resourceType: string
    resourceUrl: string
    message: string
    error?: any
}

export interface PlayerTimeTracking {
    state: 'buffering' | 'playing' | 'paused' | 'errored' | 'ended' | 'unknown'
    lastTimestamp: number | null
    watchTime: number
    bufferTime: number
}

export interface RecordingViewedSummaryAnalytics {
    // how long was the player session mounted for
    viewed_time_ms?: number
    // how long was the video playing for
    // (this could be longer than the duration, since someone could seek around multiple times)
    play_time_ms?: number
    buffer_time_ms?: number
    recording_duration_ms?: number
    recording_age_ms?: number
    recording_retention_period_days?: number
    meta_data_load_time_ms?: number
    first_snapshot_load_time_ms?: number
    first_snapshot_and_meta_load_time_ms?: number
    all_snapshots_load_time_ms?: number
    rrweb_warning_count: number
    error_count_during_recording_playback: number
    engagement_score: number
}

export interface Player {
    replayer: Replayer
    windowId: string
}

export enum SessionRecordingPlayerMode {
    Standard = 'standard',
    Sharing = 'sharing',
    Notebook = 'notebook',
    Preview = 'preview',
    Screenshot = 'screenshot',
    Video = 'video',
}

export const ModesWithInteractions = [SessionRecordingPlayerMode.Standard, SessionRecordingPlayerMode.Notebook]

export interface SessionRecordingPlayerLogicProps extends SessionRecordingDataCoordinatorLogicProps {
    playerKey: string
    sessionRecordingData?: SessionPlayerData
    matchingEventsMatchType?: MatchingEventsMatchType
    playlistLogic?: BuiltLogic<sessionRecordingsPlaylistLogicType>
    autoPlay?: boolean
    noInspector?: boolean
    mode?: SessionRecordingPlayerMode
    playerRef?: RefObject<HTMLDivElement>
    pinned?: boolean
    setPinned?: (pinned: boolean) => void
}

const ReplayIframeDatakeyPrefix = 'ph_replay_fixed_heatmap_'

// weights should add up to 1
const smoothingWeights = [
    0.07,
    0.08,
    0.1,
    0.12,
    0.26, // center point
    0.12,
    0.1,
    0.08,
    0.07,
]

const isMediaElementPlaying = (element: HTMLMediaElement): boolean =>
    !!(element.currentTime > 0 && !element.paused && !element.ended && element.readyState > 2)

function removeFromLocalStorageWithPrefix(prefix: string): void {
    for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (key?.startsWith(prefix)) {
            localStorage.removeItem(key)
        }
    }
}

export function removeReplayIframeDataFromLocalStorage(): void {
    removeFromLocalStorageWithPrefix(ReplayIframeDatakeyPrefix)
}

/**
 * returns the relative second in the recording
 * e.g. if the player starts at 1000ms and the snapshot is at 2000ms or 1500ms, the relative second is 1
 */
function toRelativeSecondInRecording(timestamp: number, playerStartTime: number): number {
    return Math.trunc((timestamp - playerStartTime) / 1000)
}

const INCREMENTAL_SNAPSHOT_EVENT_TYPE = 3
const ACTIVE_SOURCES = [
    IncrementalSource.MouseMove,
    IncrementalSource.MouseInteraction,
    IncrementalSource.Scroll,
    IncrementalSource.ViewportResize,
    IncrementalSource.Input,
    IncrementalSource.TouchMove,
    IncrementalSource.MediaInteraction,
    IncrementalSource.Drag,
]

function isUserActivity(snapshot: eventWithTime): boolean {
    return (
        snapshot.type === INCREMENTAL_SNAPSHOT_EVENT_TYPE &&
        ACTIVE_SOURCES.indexOf(snapshot.data?.source as IncrementalSource) !== -1
    )
}

const updatePlayerTimeTracking = (
    current: PlayerTimeTracking,
    newState: PlayerTimeTracking['state']
): PlayerTimeTracking => {
    // if we were just playing then update watch time
    const newWatchTime =
        current.lastTimestamp !== null && current.state === 'playing'
            ? current.watchTime + (performance.now() - current.lastTimestamp)
            : current.watchTime

    // if we were just buffering then update buffer time
    const newBufferTime =
        current.lastTimestamp !== null && current.state === 'buffering'
            ? current.bufferTime + (performance.now() - current.lastTimestamp)
            : current.bufferTime

    const newLastTimestamp = ['paused', 'ended', 'errored'].includes(newState) ? null : performance.now()

    return {
        state: newState,
        lastTimestamp: newLastTimestamp,
        watchTime: newWatchTime,
        bufferTime: newBufferTime,
    }
}

const updatePlayerTimeTrackingIfChanged = (
    current: PlayerTimeTracking,
    newState: PlayerTimeTracking['state']
): PlayerTimeTracking => {
    if (current.state === newState) {
        return current
    }

    return updatePlayerTimeTracking(current, newState)
}

function wrapFetchAndReport({
    fetch,
    onError,
}: {
    fetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    onError: (errorDetails: ResourceErrorDetails) => void
}) {
    // we wrap fetch in the player iframe so we can react to errors loading resources
    return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        try {
            const response = await fetch(input, init)
            if (!response.ok) {
                onError({
                    resourceType: 'fetch',
                    resourceUrl:
                        typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url,
                    message: `Failed to load resource: ${response.status} ${response.statusText}`,
                })
            }
            return response
        } catch (error: any) {
            console.error('Error in wrapped fetch', error)
            throw error
        }
    }
}

function isHTMLElement(target: EventTarget | null): target is HTMLElement {
    return !!target && 'tagName' in target && typeof target.tagName === 'string'
}

function isHtmlImageElement(target: HTMLElement): target is HTMLImageElement {
    return target.tagName.toLowerCase() === 'img' && 'src' in target && typeof (target as any).src === 'string'
}

function isHtmlStyleLinkElement(target: HTMLElement): target is HTMLLinkElement {
    return (
        target.tagName.toLowerCase() === 'link' &&
        'href' in target &&
        typeof (target as any).href === 'string' &&
        (target as HTMLLinkElement).rel === 'stylesheet'
    )
}

function registerErrorListeners({
    iframeWindow,
    onError,
}: {
    iframeWindow: Window
    onError: (error: ResourceErrorDetails) => void
}): () => void {
    // Create named listener functions so we can remove them later
    const resourceErrorListener = (e: ErrorEvent): void => {
        const t = e.target
        if (!isHTMLElement(t)) {
            return
        }

        const tag = t.tagName.toLowerCase()
        if (isHtmlImageElement(t)) {
            onError({
                resourceType: 'img',
                resourceUrl: t.src,
                message: 'Failed to load image',
                error: e.error,
            })
        } else if (isHtmlStyleLinkElement(t)) {
            onError({
                resourceType: 'stylesheet',
                resourceUrl: t.href,
                message: 'Failed to load stylesheet',
                error: e.error,
            })
        } else {
            onError({
                resourceType: tag,
                resourceUrl: (t as any).src || (t as any).href || '',
                message: `Failed to load resource of type ${tag}. ${typeof t}`,
                error: e,
            })
        }
    }

    const runtimeErrorListener = (e: ErrorEvent): void => {
        onError({
            resourceType: 'js',
            resourceUrl: e.filename,
            message: e.message,
            error: e.error,
        })
    }

    const cspViolationListener = (e: SecurityPolicyViolationEvent): void => {
        onError({
            resourceType: 'csp',
            resourceUrl: e.blockedURI,
            message: `CSP violation: ${e.violatedDirective}`,
            error: null,
        })
    }

    // Add listeners
    iframeWindow.addEventListener('error', resourceErrorListener, /* capture */ true)
    iframeWindow.addEventListener('error', runtimeErrorListener)
    iframeWindow.document.addEventListener('securitypolicyviolation', cspViolationListener)

    // Return cleanup function
    return () => {
        iframeWindow.removeEventListener('error', resourceErrorListener, true)
        iframeWindow.removeEventListener('error', runtimeErrorListener)
        iframeWindow.document.removeEventListener('securitypolicyviolation', cspViolationListener)
    }
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [
            snapshotDataLogic(props),
            ['snapshotsLoaded', 'snapshotsLoading', 'snapshotSources'],
            sessionRecordingDataCoordinatorLogic(props),
            [
                'urls',
                'sessionPlayerData',
                'sessionPlayerMetaData',
                'sessionPlayerMetaDataLoading',
                'createExportJSON',
                'customRRWebEvents',
                'fullyLoaded',
                'trackedWindow',
            ],
            playerSettingsLogic,
            ['speed', 'skipInactivitySetting'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            preflightLogic,
            ['preflight'],
            featureFlagLogic,
            ['featureFlags'],
            exportsLogic,
            ['hasReachedExportFullVideoLimit'],
        ],
        actions: [
            snapshotDataLogic(props),
            ['loadSnapshots', 'loadSnapshotsForSourceFailure', 'loadSnapshotSourcesFailure', 'loadUntilTimestamp'],
            sessionRecordingDataCoordinatorLogic(props),
            ['loadRecordingData', 'loadRecordingMetaSuccess', 'maybePersistRecording'],
            playerSettingsLogic,
            ['setSpeed', 'setSkipInactivitySetting'],
            sessionRecordingEventUsageLogic,
            ['reportNextRecordingTriggered', 'reportRecordingExportedToFile'],
            exportsLogic,
            ['startReplayExport'],
        ],
    })),
    actions({
        tryInitReplayer: () => true,
        setPlayer: (player: Player | null) => ({ player }),
        setPlay: true,
        setPause: true,
        setEndReached: (reached: boolean = true) => ({ reached }),
        startBuffer: true,
        endBuffer: true,
        startScrub: true,
        endScrub: true,
        setPlayerError: (reason: string) => ({ reason }),
        clearPlayerError: true,
        setSkippingInactivity: (isSkippingInactivity: boolean) => ({ isSkippingInactivity }),
        setSkippingToMatchingEvent: (isSkippingToMatchingEvent: boolean) => ({ isSkippingToMatchingEvent }),
        syncPlayerSpeed: true,
        setCurrentTimestamp: (timestamp: number) => ({ timestamp }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seekToTimestamp: (timestamp: number, forcePlay: boolean = false) => ({ timestamp, forcePlay }),
        seekToTime: (timeInMilliseconds: number) => ({ timeInMilliseconds }),
        seekForward: (amount?: number) => ({ amount }),
        seekBackward: (amount?: number) => ({ amount }),
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
        pauseIframePlayback: true,
        restartIframePlayback: true,
        setCurrentSegment: (segment: RecordingSegment) => ({ segment }),
        setRootFrame: (frame: HTMLDivElement) => ({ frame }),
        checkBufferingCompleted: true,
        initializePlayerFromStart: true,
        incrementErrorCount: true,
        incrementWarningCount: (count: number = 1) => ({ count }),
        caughtAssetErrorFromIframe: (errorDetails: ResourceErrorDetails) => ({ errorDetails }),
        syncSnapshotsWithPlayer: true,
        exportRecordingToFile: true,
        deleteRecording: true,
        openExplorer: true,
        takeScreenshot: true,
        getClip: (format: ExporterFormat, duration: number = 5, filename?: string) => ({ format, duration, filename }),
        exportRecording: (
            format: ExporterFormat,
            timestamp: number = 0,
            mode: SessionRecordingPlayerMode = SessionRecordingPlayerMode.Screenshot,
            duration: number = 5,
            filename?: string
        ) => ({ format, timestamp, mode, duration, filename }),
        closeExplorer: true,
        openHeatmap: true,
        setExplorerProps: (props: SessionRecordingPlayerExplorerProps | null) => ({ props }),
        setIsFullScreen: (isFullScreen: boolean) => ({ isFullScreen }),
        skipPlayerForward: (rrWebPlayerTime: number, skip: number) => ({ rrWebPlayerTime, skip }),
        incrementClickCount: true,
        // the error is emitted from code we don't control in rrweb, so we can't guarantee it's really an Error
        playerErrorSeen: (error: any) => ({ error }),
        fingerprintReported: (fingerprint: string) => ({ fingerprint }),
        setDebugSnapshotTypes: (types: EventType[]) => ({ types }),
        setDebugSnapshotIncrementalSources: (incrementalSources: IncrementalSource[]) => ({ incrementalSources }),
        setPlayNextAnimationInterrupted: (interrupted: boolean) => ({ interrupted }),
        setMaskWindow: (shouldMaskWindow: boolean) => ({ shouldMaskWindow }),
        setIsCommenting: (isCommenting: boolean) => ({ isCommenting }),
        schedulePlayerTimeTracking: true,
        setQuickEmojiIsOpen: (quickEmojiIsOpen: boolean) => ({ quickEmojiIsOpen }),
        updatePlayerTimeTracking: true,
        exportRecordingToVideoFile: true,
        markViewed: (delay?: number) => ({ delay }),
        setWasMarkedViewed: (wasMarkedViewed: boolean) => ({ wasMarkedViewed }),
        setShowingClipParams: (showingClipParams: boolean) => ({ showingClipParams }),
        setIsHovering: (isHovering: boolean) => ({ isHovering }),
        allowPlayerChromeToHide: true,
        setMuted: (muted: boolean) => ({ muted }),
        setSkipToFirstMatchingEvent: (skipToFirstMatchingEvent: boolean) => ({ skipToFirstMatchingEvent }),
    }),
    reducers(({ props }) => ({
        skipToFirstMatchingEvent: [
            false,
            {
                setSkipToFirstMatchingEvent: (_, { skipToFirstMatchingEvent }) => skipToFirstMatchingEvent,
            },
        ],
        showingClipParams: [
            false as boolean,
            {
                setShowingClipParams: (_, { showingClipParams }) => showingClipParams,
                setIsCommenting: (state, { isCommenting }) => (isCommenting ? false : state),
                setQuickEmojiIsOpen: (state, { quickEmojiIsOpen }) => (quickEmojiIsOpen ? false : state),
            },
        ],
        wasMarkedViewed: [
            false as boolean,
            {
                setWasMarkedViewed: (_, { wasMarkedViewed }) => wasMarkedViewed,
            },
        ],
        isCommenting: [
            false,
            {
                setIsCommenting: (_, { isCommenting }) => isCommenting,
                setShowingClipParams: (state, { showingClipParams }) => (showingClipParams ? false : state),
                setQuickEmojiIsOpen: (state, { quickEmojiIsOpen }) => (quickEmojiIsOpen ? false : state),
            },
        ],
        quickEmojiIsOpen: [
            false,
            {
                setQuickEmojiIsOpen: (_, { quickEmojiIsOpen }) => quickEmojiIsOpen,
                setShowingClipParams: (state, { showingClipParams }) => (showingClipParams ? false : state),
                setIsCommenting: (state, { isCommenting }) => (isCommenting ? false : state),
            },
        ],
        maskingWindow: [
            false,
            {
                setMaskWindow: (_, { shouldMaskWindow }) => shouldMaskWindow,
            },
        ],
        playNextAnimationInterrupted: [
            false,
            {
                setPlayNextAnimationInterrupted: (_, { interrupted }) => interrupted,
            },
        ],
        reportedReplayerErrors: [
            new Set<string>(),
            {
                fingerprintReported: (state, { fingerprint }) => {
                    const clonedSet = new Set(state)
                    clonedSet.add(fingerprint)
                    return clonedSet
                },
            },
        ],
        clickCount: [
            0,
            {
                incrementClickCount: (state) => state + 1,
            },
        ],
        rootFrame: [
            null as HTMLDivElement | null,
            {
                setRootFrame: (_, { frame }) => frame,
            },
        ],
        player: [
            null as Player | null,
            {
                setPlayer: (_, { player }) => player,
            },
        ],
        currentTimestamp: [
            undefined as number | undefined,
            {
                setCurrentTimestamp: (_, { timestamp }) => timestamp,
            },
        ],
        timestampChangeTracking: [
            // if the player gets stuck on the same timestamp we shouldn't appear to pause the replay
            // better for the replay to not get stuck but...
            { timestamp: null, timestampMatchesPrevious: 0 } as {
                timestamp: number | null
                timestampMatchesPrevious: number
            },
            {
                setCurrentTimestamp: (state, { timestamp }) => {
                    return {
                        timestamp,
                        timestampMatchesPrevious:
                            state.timestamp !== null && state.timestamp === timestamp
                                ? state.timestampMatchesPrevious + 1
                                : 0,
                    }
                },
                skipPlayerForward: () => {
                    return {
                        timestamp: null,
                        timestampMatchesPrevious: 0,
                    }
                },
            },
        ],
        currentSegment: [
            null as RecordingSegment | null,
            {
                setCurrentSegment: (_, { segment }) => segment,
            },
        ],
        isSkippingInactivity: [false, { setSkippingInactivity: (_, { isSkippingInactivity }) => isSkippingInactivity }],
        isSkippingToMatchingEvent: [
            false,
            { setSkippingToMatchingEvent: (_, { isSkippingToMatchingEvent }) => isSkippingToMatchingEvent },
        ],
        scale: [
            1,
            {
                setScale: (_, { scale }) => scale,
            },
        ],
        playingState: [
            SessionPlayerState.PLAY as SessionPlayerState.PLAY | SessionPlayerState.PAUSE,
            {
                setPlay: () => SessionPlayerState.PLAY,
                setPause: () => SessionPlayerState.PAUSE,
            },
        ],
        playingTimeTracking: [
            {
                state: 'unknown',
                lastTimestamp: null,
                watchTime: 0,
                bufferTime: 0,
            } as PlayerTimeTracking,
            {
                updatePlayerTimeTracking: (state) => {
                    // called on a timer to avoid inactive watching from not capturing a clear time
                    return ['playing', 'buffering'].includes(state.state)
                        ? updatePlayerTimeTracking(state, state.state)
                        : state
                },
                startBuffer: (state) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }
                    return updatePlayerTimeTrackingIfChanged(state, 'buffering')
                },
                endBuffer: (state) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }

                    // endBuffer is often called later than start playing, we only need to act on it, if we were just buffering
                    if (state.state !== 'buffering') {
                        return state
                    }

                    // don't change the state
                    return updatePlayerTimeTracking(state, state.state)
                },
                setPlay: (state) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }

                    return updatePlayerTimeTrackingIfChanged(state, 'playing')
                },
                setPause: (state) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }

                    return updatePlayerTimeTrackingIfChanged(state, 'paused')
                },
                setEndReached: (state, { reached }) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }

                    if (!reached) {
                        return state
                    }

                    return updatePlayerTimeTrackingIfChanged(state, 'ended')
                },
                setPlayerError: (state) => {
                    if (props.mode === SessionRecordingPlayerMode.Preview) {
                        return state
                    }

                    return updatePlayerTimeTrackingIfChanged(state, 'errored')
                },
                seekToTime: (state) => {
                    return state
                },
            },
        ],
        isBuffering: [true, { startBuffer: () => true, endBuffer: () => false }],
        playerError: [
            null as string | null,
            {
                setPlayerError: (_, { reason }) => (reason.trim().length ? reason : null),
                clearPlayerError: () => null,
            },
        ],
        isScrubbing: [false, { startScrub: () => true, endScrub: () => false }],

        errorCount: [0, { incrementErrorCount: (prevErrorCount) => prevErrorCount + 1 }],
        warningCount: [0, { incrementWarningCount: (prevWarningCount, { count }) => prevWarningCount + count }],
        endReached: [
            false,
            {
                setEndReached: (_, { reached }) => reached,
                tryInitReplayer: () => false,
                setCurrentTimestamp: () => false,
            },
        ],
        explorerMode: [
            null as SessionRecordingPlayerExplorerProps | null,
            {
                setExplorerProps: (_, { props }) => props,
                closeExplorer: () => null,
            },
        ],
        isFullScreen: [
            false,
            {
                setIsFullScreen: (_, { isFullScreen }) => isFullScreen,
            },
        ],
        debugSettings: [
            {
                types: [EventType.FullSnapshot, EventType.IncrementalSnapshot],
                incrementalSources: [IncrementalSource.Mutation],
            } as {
                types: EventType[]
                incrementalSources: IncrementalSource[]
            },
            {
                setDebugSnapshotTypes: (s, { types }) => ({ ...s, types }),
                setDebugSnapshotIncrementalSources: (s, { incrementalSources }) => ({ ...s, incrementalSources }),
            },
        ],
        isHovering: [
            false,
            {
                setIsHovering: (_, { isHovering }) => isHovering,
            },
        ],
        forceShowPlayerChrome: [
            true,
            {
                setIsHovering: (state, { isHovering }) => (isHovering ? false : state),
                allowPlayerChromeToHide: () => {
                    return false
                },
            },
        ],
        isMuted: [
            false,
            {
                setMuted: (_, { muted }) => muted,
            },
        ],
    })),
    selectors({
        // Prop references for use by other logics
        sessionRecordingId: [(_, p) => [p.sessionRecordingId], (sessionRecordingId) => sessionRecordingId],
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlayerLogicProps => props],
        playlistLogic: [() => [(_, props) => props], (props) => props.playlistLogic],

        hasSnapshots: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData) => {
                return Object.keys(sessionPlayerData.snapshotsByWindowId).length > 0
            },
        ],

        activityPerSecond: [
            (s) => [s.sessionPlayerData, s.hasSnapshots],
            (
                sessionPlayerData: SessionPlayerData,
                hasSnapshots: boolean
            ): { smoothedPoints: Record<number, { y: number }>; maxY: number; durationSeconds: number } => {
                const start = sessionPlayerData.start
                if (start === null || !hasSnapshots) {
                    return { smoothedPoints: {}, maxY: 0, durationSeconds: (sessionPlayerData?.durationMs ?? 0) / 1000 }
                }

                // First add a 0 for every second in the recording
                const rawActivity: Record<number, { y: number }> = {}
                Array.from({ length: Math.ceil(sessionPlayerData.durationMs / 1000 + 1) }, (_, i) => i).forEach(
                    (second) => {
                        rawActivity[second] = { y: 0 }
                    }
                )

                Object.entries(sessionPlayerData.snapshotsByWindowId).forEach(([_, snapshots]) => {
                    snapshots.forEach((snapshot) => {
                        const timestamp = toRelativeSecondInRecording(snapshot.timestamp, start.valueOf())

                        if (!rawActivity[timestamp]) {
                            rawActivity[timestamp] = { y: 0 }
                        }

                        if (isUserActivity(snapshot)) {
                            rawActivity[timestamp].y += 5000
                        } else if (
                            snapshot.type === EventType.IncrementalSnapshot &&
                            'source' in snapshot.data &&
                            snapshot.data.source === IncrementalSource.Mutation
                        ) {
                            rawActivity[timestamp].y +=
                                (snapshot.data.adds?.length || 0) +
                                (snapshot.data.removes?.length || 0) +
                                (snapshot.data.attributes?.length || 0) +
                                (snapshot.data.texts?.length || 0)
                        }
                    })
                })

                // Apply smoothing
                const sortedSeconds = Object.keys(rawActivity)
                    .map(Number)
                    .sort((a, b) => a - b)

                const smoothedActivity: typeof rawActivity = {}

                let maxY = 0
                sortedSeconds.forEach((second) => {
                    let smoothedY = 0
                    for (let i = -4; i <= 4; i++) {
                        const neighborSecond = second + i
                        if (rawActivity[neighborSecond]) {
                            smoothedY += rawActivity[neighborSecond].y * smoothingWeights[i + 4]
                        }
                    }
                    smoothedActivity[second] = {
                        y: smoothedY,
                    }
                    maxY = Math.max(maxY, smoothedY)
                })

                return {
                    smoothedPoints: smoothedActivity,
                    maxY,
                    durationSeconds: (sessionPlayerData?.durationMs ?? 0) / 1000,
                }
            },
        ],

        roughAnimationFPS: [(s) => [s.playerSpeed], (playerSpeed) => playerSpeed * (1000 / 60)],
        currentPlayerState: [
            (s) => [
                s.playingState,
                s.isBuffering,
                s.playerError,
                s.isScrubbing,
                s.isSkippingInactivity,
                s.isSkippingToMatchingEvent,
                s.snapshotsLoaded,
                s.snapshotsLoading,
            ],
            (
                playingState,
                isBuffering,
                playerError,
                isScrubbing,
                isSkippingInactivity,
                isSkippingToMatchingEvent,
                snapshotsLoaded,
                snapshotsLoading
            ) => {
                switch (true) {
                    case isScrubbing:
                        // If scrubbing, playingState takes precedence
                        return playingState
                    case !!playerError?.trim().length:
                        return SessionPlayerState.ERROR
                    case !snapshotsLoaded && !snapshotsLoading:
                        return SessionPlayerState.READY
                    case isSkippingToMatchingEvent && playingState !== SessionPlayerState.PAUSE:
                        return SessionPlayerState.SKIP_TO_MATCHING_EVENT
                    case isSkippingInactivity && playingState !== SessionPlayerState.PAUSE:
                        return SessionPlayerState.SKIP
                    case isBuffering:
                        return SessionPlayerState.BUFFER
                    default:
                        return playingState
                }
            },
        ],

        // Useful for the relative time in the context of the whole recording
        currentPlayerTime: [
            (s) => [s.currentTimestamp, s.sessionPlayerData],
            (currentTimestamp, sessionPlayerData) => {
                return Math.max(0, (currentTimestamp ?? 0) - (sessionPlayerData?.start?.valueOf() ?? 0))
            },
        ],

        currentPlayerTimeSeconds: [
            (s) => [s.currentPlayerTime],
            (currentPlayerTime) => Math.floor(currentPlayerTime / 1000),
        ],

        // The relative time for the player, i.e. the offset between the current timestamp, and the window start for the current segment
        toRRWebPlayerTime: [
            (s) => [s.sessionPlayerData, s.currentSegment],
            (sessionPlayerData, currentSegment) => {
                return (timestamp: number): number | undefined => {
                    if (!currentSegment || !currentSegment.windowId) {
                        return
                    }

                    const snapshots = sessionPlayerData.snapshotsByWindowId[currentSegment.windowId]

                    return Math.max(0, timestamp - snapshots[0].timestamp)
                }
            },
        ],

        // The relative time for the player, i.e. the offset between the current timestamp, and the window start for the current segment
        fromRRWebPlayerTime: [
            (s) => [s.sessionPlayerData, s.currentSegment],
            (sessionPlayerData, currentSegment) => {
                return (time?: number): number | undefined => {
                    if (time === undefined || !currentSegment?.windowId) {
                        return
                    }
                    const snapshots = sessionPlayerData.snapshotsByWindowId[currentSegment.windowId]
                    return snapshots[0].timestamp + time
                }
            },
        ],

        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],

        playerSpeed: [
            (s) => [s.speed, s.isSkippingInactivity, s.currentSegment, s.currentTimestamp, (_, props) => props.mode],
            (speed, isSkippingInactivity, currentSegment, currentTimestamp, mode) => {
                if (mode === SessionRecordingPlayerMode.Preview) {
                    // default max speed in rrweb https://github.com/rrweb-io/rrweb/blob/58c9104eddc8b7994a067a97daae5684e42f892f/packages/rrweb/src/replay/index.ts#L178
                    return 360
                }

                if (isSkippingInactivity) {
                    const secondsToSkip = ((currentSegment?.endTimestamp ?? 0) - (currentTimestamp ?? 0)) / 1000
                    return Math.max(50, secondsToSkip)
                }
                return speed
            },
        ],
        segmentForTimestamp: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData) => {
                return (timestamp?: number): RecordingSegment | null => {
                    if (timestamp === undefined) {
                        return null
                    }
                    if (sessionPlayerData.segments.length) {
                        for (const segment of sessionPlayerData.segments) {
                            if (segment.startTimestamp <= timestamp && timestamp <= segment.endTimestamp) {
                                return segment
                            }
                        }
                        return {
                            kind: 'buffer',
                            startTimestamp: timestamp,
                            endTimestamp: sessionPlayerData.segments[0].startTimestamp - 1,
                            isActive: false,
                        } as RecordingSegment
                    }
                    return null
                }
            },
        ],

        debugSnapshots: [
            (s) => [s.sessionPlayerData, s.debugSettings],
            (sessionPlayerData: SessionPlayerData, debugSettings): eventWithTime[] => {
                const allSnapshots = Object.values(sessionPlayerData.snapshotsByWindowId).flat()
                const visualSnapshots = allSnapshots.filter(
                    (s) =>
                        debugSettings.types.includes(s.type) &&
                        (s.type != EventType.IncrementalSnapshot ||
                            debugSettings.incrementalSources.includes(s.data.source))
                )
                return visualSnapshots.sort((a, b) => a.timestamp - b.timestamp)
            },
        ],

        currentURL: [
            (s) => [s.urls, s.sessionPlayerMetaData, s.currentTimestamp],
            (urls, sessionPlayerMetaData, currentTimestamp): string | undefined => {
                if (!urls.length || !currentTimestamp) {
                    return sessionPlayerMetaData?.start_url ?? undefined
                }

                // Go through the events in reverse to find the latest pageview
                for (let i = urls.length - 1; i >= 0; i--) {
                    const urlTimestamp = urls[i]
                    if (i === 0 || urlTimestamp.timestamp < currentTimestamp) {
                        return urlTimestamp.url
                    }
                }
            },
        ],
        resolution: [
            (s) => [s.sessionPlayerData, s.currentTimestamp, s.currentSegment],
            (sessionPlayerData, currentTimestamp, currentSegment): { width: number; height: number } | null => {
                // Find snapshot to pull resolution from
                if (!currentTimestamp) {
                    return null
                }
                const snapshots = sessionPlayerData.snapshotsByWindowId[currentSegment?.windowId ?? ''] ?? []

                const currIndex = findLastIndex(
                    snapshots,
                    (s: eventWithTime) => s.timestamp < currentTimestamp && (s.data as any).width
                )

                if (currIndex === -1) {
                    return null
                }
                const snapshot = snapshots[currIndex]

                const resolution = {
                    width: snapshot.data?.['width'],
                    height: snapshot.data?.['height'],
                }

                // For video export: expose resolution via global variable
                if (typeof window !== 'undefined') {
                    ;(window as any).__POSTHOG_RESOLUTION__ = resolution
                }

                return resolution
            },
            {
                resultEqualityCheck: (prev, next) => {
                    // Only update if the resolution values have changed (not the object reference)
                    // stops PlayerMeta from re-rendering on every player position
                    return objectsEqual(prev, next)
                },
            },
        ],
        hoverModeIsEnabled: [
            (s) => [s.logicProps, s.isCommenting, s.showingClipParams],
            (logicProps, isCommenting, showingClipParams): boolean => {
                return (
                    !!logicProps.mode &&
                    ModesWithInteractions.includes(logicProps.mode) &&
                    !isCommenting &&
                    !showingClipParams
                )
            },
        ],
        showPlayerChrome: [
            (s) => [s.hoverModeIsEnabled, s.isHovering, s.forceShowPlayerChrome],
            (hoverModeIsEnabled, isHovering, forceShowPlayerChrome): boolean => {
                if (!hoverModeIsEnabled) {
                    // we always show the UI in non-hover mode
                    return true
                }

                // we default to showing the UI until a timer hides it
                // or the user has hovered over the player
                if (forceShowPlayerChrome) {
                    return true
                }
                return isHovering
            },
        ],

        // Target timestamp to buffer ahead to (current position + 15 minutes)
        targetBufferTimestamp: [
            (s) => [s.currentTimestamp],
            (currentTimestamp): number | null => {
                if (!currentTimestamp) {
                    return null
                }

                return currentTimestamp + DEFAULT_LOADING_BUFFER
            },
        ],
    }),
    listeners(({ props, values, actions, cache }) => ({
        caughtAssetErrorFromIframe: ({ errorDetails }) => {
            // eslint-disable-next-line no-console
            console.log('caughtAssetErrorFromIframe', errorDetails)
        },
        [playerCommentModel.actionTypes.startCommenting]: async ({ comment }) => {
            actions.setIsCommenting(true)
            if (comment) {
                // and we need a short wait until the logic is mounted after calling setIsCommenting
                const waitForLogic = async (): Promise<BuiltLogic<playerCommentOverlayLogicType> | null> => {
                    for (let attempts = 0; attempts < 5; attempts++) {
                        const theMountedLogic = playerCommentOverlayLogic.findMounted({
                            recordingId: props.sessionRecordingId,
                            ...props,
                        })
                        if (theMountedLogic) {
                            return theMountedLogic
                        }
                        await new Promise((resolve) => setTimeout(resolve, 100))
                    }
                    return null
                }

                const theMountedLogic = await waitForLogic()

                if (theMountedLogic) {
                    theMountedLogic.actions.editComment(comment)
                } else {
                    lemonToast.error('Could not start editing that comment 😓, please refresh the page and try again.')
                }
            }
        },
        setIsCommenting: ({ isCommenting }) => {
            if (isCommenting) {
                actions.setPause()
            } else {
                actions.setPlay()
            }
        },
        playerErrorSeen: ({ error }) => {
            const fingerprint = encodeURIComponent(error.message + error.filename + error.lineno + error.colno)
            if (values.reportedReplayerErrors.has(fingerprint)) {
                return
            }
            const extra = { fingerprint, playbackSessionId: values.sessionRecordingId }
            posthog.captureException(error, {
                ...extra,
                feature: 'replayer error swallowed',
            })
            if (posthog.config.debug) {
                posthog.capture('replayer error swallowed', extra)
            }
            actions.fingerprintReported(fingerprint)
        },
        skipPlayerForward: ({ rrWebPlayerTime, skip }) => {
            // if the player has got stuck on the same timestamp for several animation frames
            // then we skip ahead a little to get past the blockage
            // this is a KLUDGE to get around what might be a bug in rrweb
            values.player?.replayer?.play(rrWebPlayerTime + skip)
            posthog.capture('stuck session player skipped forward', {
                sessionId: values.sessionRecordingId,
                rrWebTime: rrWebPlayerTime,
            })
        },
        setRootFrame: () => {
            actions.tryInitReplayer()
        },
        tryInitReplayer: () => {
            // Tries to initialize a new player
            const windowId = values.segmentForTimestamp(values.currentTimestamp)?.windowId

            actions.setPlayer(null)

            if (values.rootFrame) {
                values.rootFrame.innerHTML = '' // Clear the previously drawn frames
            }

            if (
                !values.rootFrame ||
                windowId === undefined ||
                !values.sessionPlayerData.snapshotsByWindowId[windowId] ||
                values.sessionPlayerData.snapshotsByWindowId[windowId].length < 2
            ) {
                actions.setPlayer(null)
                return
            }

            const plugins: ReplayPlugin[] = [HLSPlayerPlugin]

            // We don't want non-cloud products to talk to our proxy as it likely won't work, but we _do_ want local testing to work
            if (values.preflight?.cloud || window.location.hostname === 'localhost') {
                plugins.push(CorsPlugin)
            }

            plugins.push(CanvasReplayerPlugin(values.sessionPlayerData.snapshotsByWindowId[windowId]))
            plugins.push(AudioMuteReplayerPlugin(values.isMuted))

            // we override the console in the player, with one which stores its data instead of logging
            // there is a debounced logger hidden inside that.
            // rrweb can log so much that it becomes a performance issue
            // this overridden logging avoids some recordings freezing the browser
            // outside of standard mode, we swallow the logs completely
            const logging =
                props.mode === SessionRecordingPlayerMode.Standard
                    ? makeLogger(actions.incrementWarningCount)
                    : makeNoOpLogger()

            cache.disposables.add(() => {
                return () => {
                    Object.values(logging.timers as BuiltLogging['timers']).forEach((timer) => {
                        if (timer) {
                            clearTimeout(timer)
                        }
                    })
                    ;(window as any)[`__posthog_player_logs`] = undefined
                    ;(window as any)[`__posthog_player_warnings`] = undefined
                }
            }, 'consoleTimers')

            const config: Partial<playerConfig> & { onError: (error: any) => void } = {
                root: values.rootFrame,
                ...COMMON_REPLAYER_CONFIG,
                // these two settings are attempts to improve performance of running two Replayers at once
                // the main player and a preview player
                mouseTail: props.mode !== SessionRecordingPlayerMode.Preview,
                useVirtualDom: false,
                plugins,
                onError: (error) => {
                    actions.playerErrorSeen(error)
                },
                logger: logging.logger,
            }
            const replayer = new Replayer(values.sessionPlayerData.snapshotsByWindowId[windowId], config)

            // Listen for resource errors from rrweb
            replayer.on('fullsnapshot-rebuilded', () => {
                const iframeContentWindow = replayer.iframe.contentWindow
                const iframeFetch = replayer.iframe.contentWindow?.fetch

                if (iframeFetch && !(iframeFetch as any).__isWrappedForErrorReporting && iframeContentWindow) {
                    // We have to monkey patch fetch as rrweb doesn't provide a way to listen for these errors
                    // We do this after every fullsnapshot-rebuilded as rrweb creates a new iframe each time
                    const originalFetch = iframeFetch
                    const windowRef = new WeakRef(iframeContentWindow)

                    iframeContentWindow.fetch = wrapFetchAndReport({
                        fetch: iframeFetch,
                        onError: (errorDetails: ResourceErrorDetails) => {
                            actions.caughtAssetErrorFromIframe(errorDetails)
                        },
                    })
                    ;(iframeContentWindow.fetch as any).__isWrappedForErrorReporting = true

                    cache.disposables.add(() => {
                        return () => {
                            const window = windowRef.deref()
                            if (window && window.fetch) {
                                window.fetch = originalFetch
                                delete (window.fetch as any).__isWrappedForErrorReporting
                            }
                        }
                    }, 'iframeFetchWrapper')
                }

                if (iframeContentWindow) {
                    cache.disposables.add(() => {
                        return registerErrorListeners({
                            iframeWindow: iframeContentWindow,
                            onError: (error) => actions.caughtAssetErrorFromIframe(error),
                        })
                    }, 'iframeErrorListeners')
                }
            })

            actions.setPlayer({ replayer, windowId })
        },
        setPlayer: ({ player }) => {
            if (player) {
                if (values.currentTimestamp !== undefined) {
                    actions.seekToTimestamp(values.currentTimestamp)
                }
                actions.syncPlayerSpeed()
            }
        },
        setCurrentSegment: ({ segment }) => {
            // Check if we should we skip this segment
            if (!segment.isActive && values.skipInactivitySetting && segment.kind !== 'buffer') {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }

            // Check if the new segment is for a different window_id than the last one
            // If so, we need to re-initialize the player
            if (!values.player || values.player.windowId !== segment.windowId) {
                values.player?.replayer?.pause()
                actions.tryInitReplayer()
            }
            if (values.currentTimestamp !== undefined) {
                actions.seekToTimestamp(values.currentTimestamp)
            }
        },
        setSkipInactivitySetting: ({ skipInactivitySetting }) => {
            if (!values.currentSegment?.isActive && skipInactivitySetting) {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }
        },
        setSkippingInactivity: () => {
            actions.syncPlayerSpeed()
        },
        syncPlayerSpeed: () => {
            values.player?.replayer?.setConfig({ speed: values.playerSpeed })
        },
        checkBufferingCompleted: () => {
            // If buffering has completed, resume last playing state
            if (values.currentTimestamp === undefined) {
                return
            }
            const isBuffering = values.segmentForTimestamp(values.currentTimestamp)?.kind === 'buffer'

            if (values.currentPlayerState === SessionPlayerState.BUFFER && !isBuffering) {
                actions.endBuffer()
                actions.seekToTimestamp(values.currentTimestamp)
            }
        },
        initializePlayerFromStart: () => {
            const initialSegment = values.sessionPlayerData?.segments[0]
            if (initialSegment) {
                // Check for the "t" search param in the url on first load
                if (!cache.hasInitialized) {
                    cache.hasInitialized = true
                    const searchParams = router.values.searchParams
                    if (searchParams.fullscreen) {
                        actions.setIsFullScreen(true)
                    }
                    if (searchParams.timestamp) {
                        const desiredStartTime = Number(searchParams.timestamp)
                        actions.seekToTimestamp(desiredStartTime, true)
                    } else if (searchParams.t) {
                        const desiredStartTime = Number(searchParams.t) * 1000
                        actions.seekToTime(desiredStartTime)
                    } else {
                        actions.setSkipToFirstMatchingEvent(true)
                    }
                }

                if (!values.currentTimestamp) {
                    actions.setCurrentTimestamp(initialSegment.startTimestamp)
                }

                actions.setCurrentSegment(initialSegment)
            }
        },
        syncSnapshotsWithPlayer: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.player?.replayer?.service.state.context.events ?? []
            const eventsToAdd = []

            if (values.currentSegment?.windowId !== undefined) {
                // TODO: Probably need to check for de-dupes here....
                // TODO: We do some sorting and rearranging in the data logic... We may need to handle that here, replacing the
                // whole events stream....
                eventsToAdd.push(
                    ...(values.sessionPlayerData.snapshotsByWindowId[values.currentSegment?.windowId] ?? []).slice(
                        currentEvents.length
                    )
                )
            }

            // If replayer isn't initialized, it will be initialized with the already loaded snapshots
            if (values.player?.replayer) {
                for (const event of eventsToAdd) {
                    values.player?.replayer?.addEvent(event)
                }
            }

            if (!values.currentTimestamp) {
                actions.initializePlayerFromStart()
            }
            actions.checkBufferingCompleted()
            breakpoint()
        },
        loadRecordingMetaSuccess: () => {
            // As the connected data logic may be preloaded we call a shared function here and on mount
            actions.syncSnapshotsWithPlayer()

            if (props.autoPlay) {
                // Autoplay assumes we are playing immediately so lets go ahead and load more data
                actions.setPlay()

                if (router.values.searchParams.pause) {
                    setTimeout(() => {
                        /** KLUDGE: when loaded for visual regression tests we want to pause the player
                         ** but only after it has had time to buffer and show the frame
                         *
                         * Frustratingly if we start paused we never process the data,
                         * so the player frame is just a black square.
                         *
                         * If we play (the default behaviour) and then stop after its processed the data
                         * then we see the player screen
                         * and can assert that _at least_ the full snapshot has been processed
                         * (i.e. we didn't completely break rrweb playback)
                         *
                         * We have to be paused so that the visual regression snapshot doesn't flap
                         * (because of the seekbar timestamp changing)
                         *
                         * And don't want to be at 0, so we can see that the seekbar
                         * at least paints the "played" portion of the recording correctly
                         **/
                        actions.setPause()
                    }, 400)
                }
            }
        },
        loadSnapshotsForSourceFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                console.error('PostHog Recording Playback Error: No snapshots loaded')
                actions.setPlayerError('loadSnapshotsForSourceFailure')
            }
        },
        loadSnapshotSourcesFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                console.error('PostHog Recording Playback Error: No snapshots loaded')
                actions.setPlayerError('loadSnapshotSourcesFailure')
            }
        },
        setPlay: () => {
            if (!values.snapshotsLoaded) {
                actions.loadSnapshots()
            }

            actions.stopAnimation()
            actions.restartIframePlayback()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change

            // Use the start of the current segment if there is no currentTimestamp
            // (theoretically, should never happen, but Typescript doesn't know that)

            let nextTimestamp = values.currentTimestamp || values.currentSegment?.startTimestamp

            if (values.endReached) {
                nextTimestamp = values.sessionPlayerData.segments[0].startTimestamp
            }

            actions.setEndReached(false)

            if (nextTimestamp !== undefined) {
                actions.seekToTimestamp(nextTimestamp, true)
            }
        },
        markViewed: async ({ delay }, breakpoint) => {
            breakpoint()
            if (
                props.playerKey?.startsWith('file-') ||
                values.wasMarkedViewed ||
                (props.mode && !ModesWithInteractions.includes(props.mode))
            ) {
                return
            }

            actions.setWasMarkedViewed(true) // this prevents us from calling the function multiple times

            await breakpoint(IS_TEST_MODE ? 1 : (delay ?? 3000))
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
        setPause: () => {
            actions.stopAnimation()
            actions.pauseIframePlayback()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change
            values.player?.replayer?.pause()
        },
        setEndReached: ({ reached }) => {
            if (reached) {
                actions.setPause()
                // TODO: this will be time-gated so won't happen immediately, but we need it to
                if (!values.wasMarkedViewed) {
                    actions.markViewed(0)
                }
            }
        },
        startBuffer: () => {
            actions.stopAnimation()
        },
        setPlayerError: () => {
            actions.incrementErrorCount()
            actions.stopAnimation()
        },
        startScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: () => {
            if (props.mode !== SessionRecordingPlayerMode.Preview) {
                actions.syncPlayerSpeed()
            }
        },
        seekToTimestamp: ({ timestamp, forcePlay }, breakpoint) => {
            actions.stopAnimation()
            actions.pauseIframePlayback()

            cache.pausedMediaElements = []
            actions.setCurrentTimestamp(timestamp)

            // Check if we're seeking to a new segment
            const segment = values.segmentForTimestamp(timestamp)

            if (segment && !objectsEqual(segment, values.currentSegment)) {
                actions.setCurrentSegment(segment)
            }

            // If next time is greater than last buffered time, set to buffering
            else if (segment?.kind === 'buffer') {
                const isPastEnd = values.sessionPlayerData.end && timestamp >= values.sessionPlayerData.end.valueOf()
                if (isPastEnd) {
                    actions.setEndReached(true)
                } else {
                    values.player?.replayer?.pause()
                    actions.startBuffer()
                    actions.clearPlayerError()
                    // the target buffer timestamp won't have been updated yet, so we calculate it directly
                    actions.loadUntilTimestamp(timestamp + DEFAULT_LOADING_BUFFER)
                }
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                // NOTE: when we show a preview pane, this branch runs
                // in very large recordings this call to pause
                // can consume 100% CPU and freeze the entire page
                values.player?.replayer?.pause(values.toRRWebPlayerTime(timestamp))
                actions.endBuffer()
                actions.clearPlayerError()
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(values.toRRWebPlayerTime(timestamp))
                actions.updateAnimation()
                actions.endBuffer()
                actions.clearPlayerError()
            }

            breakpoint()
        },
        seekForward: ({ amount = values.jumpTimeMs }) => {
            actions.seekToTime((values.currentPlayerTime || 0) + amount)
        },
        seekBackward: ({ amount = values.jumpTimeMs }) => {
            actions.seekToTime((values.currentPlayerTime || 0) - amount)
        },

        seekToTime: ({ timeInMilliseconds }) => {
            if (values.currentTimestamp === undefined) {
                return
            }

            if (!values.sessionPlayerData.start || !values.sessionPlayerData.end) {
                return
            }

            const newTimestamp = clamp(
                values.sessionPlayerData.start.valueOf() + timeInMilliseconds,
                values.sessionPlayerData.start.valueOf(),
                values.sessionPlayerData.end.valueOf()
            )

            actions.seekToTimestamp(newTimestamp)
        },

        togglePlayPause: () => {
            // If paused, start playing
            if (values.playingState === SessionPlayerState.PAUSE) {
                actions.setPlay()
            }
            // If playing, pause
            else {
                actions.setPause()
            }
        },
        updateAnimation: () => {
            // The main loop of the player. Called on each frame
            const rrwebPlayerTime = values.player?.replayer?.getCurrentTime()
            let newTimestamp = values.fromRRWebPlayerTime(rrwebPlayerTime)

            if (newTimestamp == undefined && values.currentTimestamp) {
                // This can happen if the player is not loaded due to us being in a "gap" segment
                // In this case, we should progress time forward manually
                if (values.currentSegment?.kind === 'gap') {
                    newTimestamp = values.currentTimestamp + values.roughAnimationFPS
                }
            }

            // Tell the data logic what timestamp we want buffered to
            // It will decide if it needs to load more data
            actions.loadUntilTimestamp(values.targetBufferTimestamp)

            // If we're beyond buffered position, set to buffering
            if (values.currentSegment?.kind === 'buffer') {
                // Pause only the animation, not our player, so it will restart
                // when the buffering progresses
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.clearPlayerError()
                return
            }

            if (newTimestamp == undefined) {
                // no newTimestamp is unexpected, bail out
                return
            }

            // If we are beyond the current segment then move to the next one
            if (values.currentSegment && newTimestamp > values.currentSegment.endTimestamp) {
                const nextSegment = values.segmentForTimestamp(newTimestamp)

                if (nextSegment) {
                    actions.setCurrentTimestamp(Math.max(newTimestamp, nextSegment.startTimestamp))
                    actions.setCurrentSegment(nextSegment)
                } else {
                    // At the end of the recording. Pause the player and set fully to the end
                    actions.setEndReached()
                }
                return
            }

            if (
                values.trackedWindow &&
                values.currentSegment &&
                values.currentSegment.windowId !== values.trackedWindow
            ) {
                actions.setSkippingInactivity(true)
                actions.setMaskWindow(true)
            } else {
                actions.setMaskWindow(false)
            }

            // The normal loop. Progress the player position and continue the loop
            actions.setCurrentTimestamp(newTimestamp)

            cache.disposables.add(() => {
                const timerId = requestAnimationFrame(actions.updateAnimation)
                return () => cancelAnimationFrame(timerId)
            }, 'animationTimer')
        },
        stopAnimation: () => {
            cache.disposables.dispose('animationTimer')
        },
        pauseIframePlayback: () => {
            const iframe = values.rootFrame?.querySelector('iframe')
            const iframeDocument = iframe?.contentWindow?.document
            if (!iframeDocument) {
                return
            }

            const audioElements = Array.from(iframeDocument.getElementsByTagName('audio')) as HTMLAudioElement[]
            const videoElements = Array.from(iframeDocument.getElementsByTagName('video')) as HTMLVideoElement[]
            const mediaElements: HTMLMediaElement[] = [...audioElements, ...videoElements]
            const playingElements = mediaElements.filter(isMediaElementPlaying)

            mediaElements.forEach((el) => el.pause())
            cache.pausedMediaElements = values.endReached ? [] : playingElements
        },
        restartIframePlayback: () => {
            cache.pausedMediaElements?.forEach((el: HTMLMediaElement) => el.play())
            cache.pausedMediaElements = []
        },

        exportRecordingToFile: async () => {
            if (!values.sessionPlayerData) {
                return
            }

            if (!values.user?.is_impersonated && !values.hasAvailableFeature(AvailableFeature.RECORDINGS_FILE_EXPORT)) {
                openBillingPopupModal({
                    title: 'Unlock recording exports',
                    description:
                        'Export recordings to a file that can be stored wherever you like and loaded back into PostHog for playback at any time.',
                })
                return
            }

            const doExport = async (): Promise<void> => {
                const delayTime = 1000
                let maxWaitTime = 30000
                while (!values.sessionPlayerData.fullyLoaded) {
                    if (maxWaitTime <= 0) {
                        throw new Error('Timeout waiting for recording to load')
                    }
                    maxWaitTime -= delayTime
                    await delay(delayTime)
                }

                const payload = values.createExportJSON()
                const recordingFile = new File(
                    [JSON.stringify(payload, null, 2)],
                    `export-${props.sessionRecordingId}-ph-recording.json`,
                    { type: 'application/json' }
                )

                downloadFile(recordingFile)
                actions.reportRecordingExportedToFile()
            }

            await lemonToast.promise(doExport(), {
                success: 'Export complete!',
                error: 'Export failed!',
                pending: 'Exporting recording...',
            })
        },
        deleteRecording: async () => {
            await deleteRecording(props.sessionRecordingId)

            if (props.playlistLogic) {
                props.playlistLogic.actions.loadAllRecordings()
                // Reset selected recording to first one in the list
                props.playlistLogic.actions.setSelectedRecordingId(null)
            } else if (router.values.location.pathname.includes('/replay')) {
                // On a page that displays a single recording `replay/:id` that doesn't contain a list
                router.actions.push(urls.replay())
            } else {
                // No-op a modal session recording. Delete icon is hidden in modal contexts since modals should be read only views.
            }
        },
        openExplorer: () => {
            actions.setPause()
            const iframe = values.rootFrame?.querySelector('iframe')
            const iframeHtml = iframe?.contentWindow?.document?.documentElement?.innerHTML
            if (!iframeHtml) {
                return
            }

            actions.setExplorerProps({
                html: iframeHtml,
                width: parseFloat(iframe.width),
                height: parseFloat(iframe.height),
            })
        },
        exportRecording: ({
            format,
            timestamp = 0,
            mode = SessionRecordingPlayerMode.Screenshot,
            duration = 5,
            filename = '',
        }) => {
            actions.setPause()
            const iframe = values.rootFrame?.querySelector('iframe')
            if (!iframe) {
                lemonToast.error('Cannot export recording. Please try again.')
                return
            }

            actions.startReplayExport(values.sessionRecordingId, format, timestamp, duration, mode, {
                width: iframe?.width ? Number(iframe.width) : 1400,
                height: iframe?.height ? Number(iframe.height) : 600,
                css_selector: '.replayer-wrapper',
                filename: filename || `replay-${values.sessionRecordingId}-${dayjs().format('YYYY-MM-DD-HH-mm')}`,
            })
        },
        takeScreenshot: async () => {
            // We need to subtract 1 second as the player starts immediately
            const timestamp = Math.max(0, getCurrentPlayerTime(values.logicProps) - 1)
            actions.exportRecording(ExporterFormat.PNG, timestamp, SessionRecordingPlayerMode.Screenshot)
        },
        getClip: async ({ format, duration = 5, filename }) => {
            // Center the clip around current time, minus 1 second offset for player start
            const timestamp = Math.max(
                0,
                Math.floor(getCurrentPlayerTime(values.logicProps) - 1 - Math.floor(duration / 2))
            )
            actions.exportRecording(format, timestamp, SessionRecordingPlayerMode.Screenshot, duration, filename)
        },
        exportRecordingToVideoFile: async () => {
            const duration = values.sessionPlayerData?.durationMs
                ? Math.floor(values.sessionPlayerData?.durationMs / 1000)
                : 5

            actions.exportRecording(ExporterFormat.MP4, 0, SessionRecordingPlayerMode.Video, duration)
        },
        openHeatmap: () => {
            actions.setPause()
            const iframe = values.rootFrame?.querySelector('iframe')
            const iframeHtml = iframe?.contentWindow?.document?.documentElement?.innerHTML
            const resolution = values.resolution
            if (!iframeHtml || !resolution) {
                return
            }

            removeFromLocalStorageWithPrefix(ReplayIframeDatakeyPrefix)
            const key = ReplayIframeDatakeyPrefix + uuid()
            const data: ReplayIframeData = {
                html: iframeHtml,
                width: resolution.width,
                height: resolution.height,
                startDateTime: values.sessionPlayerMetaData?.start_time,
                url: values.currentURL,
            }
            localStorage.setItem(key, JSON.stringify(data))
            router.actions.push(urls.heatmaps(`iframeStorage=${key}`))
        },

        setIsFullScreen: async ({ isFullScreen }) => {
            if (isFullScreen) {
                try {
                    await props.playerRef?.current?.requestFullscreen()
                } catch (e) {
                    console.warn('Failed to enable native full-screen mode:', e)
                }
            } else if (document.fullscreenElement === props.playerRef?.current) {
                await document.exitFullscreen()
            }
        },
        schedulePlayerTimeTracking: () => {
            const currentState = values.playingTimeTracking.state
            const interval = currentState === 'playing' ? 5000 : 30000

            cache.disposables.add(() => {
                const timerId = setTimeout(() => {
                    actions.updatePlayerTimeTracking()
                    actions.schedulePlayerTimeTracking()
                }, interval)
                return () => clearTimeout(timerId)
            }, 'playerTimeTracking')
        },
        setMuted: () => {
            // If we have an active player, reinitialize it with the new mute state
            // The AudioMuteReplayerPlugin will be recreated with the updated mute state
            if (values.player) {
                actions.tryInitReplayer()
            }
        },
    })),

    subscriptions(({ actions, values }) => ({
        sessionPlayerData: (value, oldValue) => {
            const hasSnapshotChanges = value?.snapshotsByWindowId !== oldValue?.snapshotsByWindowId

            // TODO: Detect if the order of the current window has changed (this would require re-initializing the player)

            if (hasSnapshotChanges) {
                actions.syncSnapshotsWithPlayer()
            }
        },
        timestampChangeTracking: (value) => {
            if (value.timestampMatchesPrevious < 10) {
                return
            }

            const rrwebPlayerTime = values.player?.replayer?.getCurrentTime()

            if (rrwebPlayerTime !== undefined && values.currentPlayerState === SessionPlayerState.PLAY) {
                actions.skipPlayerForward(rrwebPlayerTime, values.roughAnimationFPS)
            }
        },
        playerError: (value) => {
            if (value) {
                posthog.capture('recording player error', {
                    watchedSessionId: values.sessionRecordingId,
                    currentTimestamp: values.currentTimestamp,
                    currentSegment: values.currentSegment,
                    currentPlayerTime: values.currentPlayerTime,
                    error: value,
                })
            }
        },
        currentPlayerState: (value) => {
            if (value === SessionPlayerState.PLAY && !values.wasMarkedViewed) {
                actions.markViewed(0)
            }
        },
    })),

    beforeUnmount(({ values, actions, cache, props }) => {
        if (props.mode === SessionRecordingPlayerMode.Preview) {
            values.player?.replayer?.destroy()
            return
        }

        actions.stopAnimation()

        cache.hasInitialized = false
        cache.pausedMediaElements = []
        values.player?.replayer?.destroy()
        actions.setPlayer(null)

        try {
            terminateTestWorker()
        } catch (error) {
            console.warn('[SessionRecordingPlayerLogic] Failed to terminate test worker:', error)
        }

        const playTimeMs = values.playingTimeTracking.watchTime || 0
        const summaryAnalytics: RecordingViewedSummaryAnalytics = {
            viewed_time_ms: cache.openTime !== undefined ? performance.now() - cache.openTime : undefined,
            play_time_ms: playTimeMs,
            buffer_time_ms: values.playingTimeTracking.bufferTime || 0,
            recording_duration_ms: values.sessionPlayerData ? values.sessionPlayerData.durationMs : undefined,
            recording_age_ms:
                values.sessionPlayerData && values.sessionPlayerData.segments.length > 0
                    ? Math.floor(now().diff(values.sessionPlayerData.start, 'millisecond') ?? 0)
                    : undefined,
            recording_retention_period_days: values.sessionPlayerData.sessionRetentionPeriodDays ?? undefined,
            rrweb_warning_count: values.warningCount,
            error_count_during_recording_playback: values.errorCount,
            // as a starting and very loose measure of engagement, we count clicks
            engagement_score: values.clickCount,
        }
        posthog.capture(
            playTimeMs === 0 ? 'recording viewed with no playtime summary' : 'recording viewed summary',
            summaryAnalytics
        )
    }),

    afterMount(({ props, actions, cache }) => {
        if (props.mode === SessionRecordingPlayerMode.Preview || props.sessionRecordingId.trim() === '') {
            return
        }

        cache.pausedMediaElements = []
        cache.disposables.add(() => {
            const fullScreenListener = (): void => {
                actions.setIsFullScreen(document.fullscreenElement !== null)
            }
            document.addEventListener('fullscreenchange', fullScreenListener)
            return () => document.removeEventListener('fullscreenchange', fullScreenListener)
        }, 'fullscreenListener')

        try {
            const testWorker = getTestWorkerManager()
            void testWorker.initialize()
        } catch (error) {
            console.warn('[SessionRecordingPlayerLogic] Failed to initialize test worker:', error)
        }

        if (props.sessionRecordingId) {
            actions.loadRecordingData()
        }

        cache.openTime = performance.now()
        // we rely on actions hitting a reducer to update the timer
        // let's ping it once in a while so that if the user
        // is autoplaying and doesn't interact we get a more recent value
        actions.schedulePlayerTimeTracking()
    }),
])

export const getCurrentPlayerTime = (logicProps: SessionRecordingPlayerLogicProps): number => {
    // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
    const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
    return Math.floor(playerTime / 1000)
}
