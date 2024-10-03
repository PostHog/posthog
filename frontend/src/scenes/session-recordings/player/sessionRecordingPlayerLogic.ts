import { lemonToast } from '@posthog/lemon-ui'
import { customEvent, EventType, eventWithTime, IncrementalSource } from '@rrweb/types'
import { captureException } from '@sentry/react'
import {
    actions,
    afterMount,
    beforeUnmount,
    BuiltLogic,
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
import { now } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clamp, downloadFile } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { wrapConsole } from 'lib/utils/wrapConsole'
import posthog from 'posthog-js'
import { RefObject } from 'react'
import { Replayer } from 'rrweb'
import { playerConfig, ReplayPlugin } from 'rrweb/typings/types'
import { openBillingPopupModal } from 'scenes/billing/BillingPopup'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import {
    sessionRecordingDataLogic,
    SessionRecordingDataLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, RecordingSegment, SessionPlayerData, SessionPlayerState } from '~/types'

import type { sessionRecordingsPlaylistLogicType } from '../playlist/sessionRecordingsPlaylistLogicType'
import { playerSettingsLogic } from './playerSettingsLogic'
import { COMMON_REPLAYER_CONFIG, CorsPlugin, HLSPlayerPlugin } from './rrweb'
import { CanvasReplayerPlugin } from './rrweb/canvas/canvas-plugin'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { deleteRecording } from './utils/playerUtils'
import { SessionRecordingPlayerExplorerProps } from './view-explorer/SessionRecordingPlayerExplorer'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 3, 4, 8, 16]
export const ONE_FRAME_MS = 100 // We don't really have frames but this feels granular enough

export interface RecordingViewedSummaryAnalytics {
    // how long was the player session mounted for
    viewed_time_ms?: number
    // how long was the video playing for
    // (this could be longer than the duration, since someone could seek around multiple times)
    play_time_ms?: number
    buffer_time_ms?: number
    recording_duration_ms?: number
    recording_age_ms?: number
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
}

export interface SessionRecordingPlayerLogicProps extends SessionRecordingDataLogicProps {
    playerKey: string
    sessionRecordingData?: SessionPlayerData
    matchingEventsMatchType?: MatchingEventsMatchType
    playlistLogic?: BuiltLogic<sessionRecordingsPlaylistLogicType>
    autoPlay?: boolean
    mode?: SessionRecordingPlayerMode
    playerRef?: RefObject<HTMLDivElement>
    pinned?: boolean
    setPinned?: (pinned: boolean) => void
}

const isMediaElementPlaying = (element: HTMLMediaElement): boolean =>
    !!(element.currentTime > 0 && !element.paused && !element.ended && element.readyState > 2)

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            [
                'snapshotsLoaded',
                'snapshotsLoading',
                'isRealtimePolling',
                'sessionPlayerData',
                'sessionPlayerMetaData',
                'sessionPlayerMetaDataLoading',
                'createExportJSON',
                'customRRWebEvents',
                'fullyLoaded',
                'wasMarkedViewed',
            ],
            playerSettingsLogic,
            ['speed', 'skipInactivitySetting', 'showMouseTail'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            preflightLogic,
            ['preflight'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            sessionRecordingDataLogic(props),
            [
                'maybeLoadRecordingMeta',
                'loadSnapshots',
                'loadSnapshotsForSourceFailure',
                'loadSnapshotSourcesFailure',
                'loadRecordingMetaSuccess',
                'maybePersistRecording',
                'setWasMarkedViewed',
                'markViewed',
            ],
            playerSettingsLogic,
            ['setSpeed', 'setSkipInactivitySetting'],
            eventUsageLogic,
            [
                'reportNextRecordingTriggered',
                'reportRecordingPlayerSkipInactivityToggled',
                'reportRecordingPlayerSpeedChanged',
                'reportRecordingExportedToFile',
            ],
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
        setErrorPlayerState: (show: boolean) => ({ show }),
        setSkippingInactivity: (isSkippingInactivity: boolean) => ({ isSkippingInactivity }),
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
        syncSnapshotsWithPlayer: true,
        exportRecordingToFile: (exportUntransformedMobileData?: boolean) => ({ exportUntransformedMobileData }),
        deleteRecording: true,
        openExplorer: true,
        closeExplorer: true,
        setExplorerProps: (props: SessionRecordingPlayerExplorerProps | null) => ({ props }),
        setIsFullScreen: (isFullScreen: boolean) => ({ isFullScreen }),
        skipPlayerForward: (rrWebPlayerTime: number, skip: number) => ({ rrWebPlayerTime, skip }),
        incrementClickCount: true,
        // the error is emitted from code we don't control in rrweb, so we can't guarantee it's really an Error
        playerErrorSeen: (error: any) => ({ error }),
        fingerprintReported: (fingerprint: string) => ({ fingerprint }),
        reportMessageTooLargeWarningSeen: (sessionRecordingId: string) => ({ sessionRecordingId }),
        setDebugSnapshotTypes: (types: EventType[]) => ({ types }),
        setDebugSnapshotIncrementalSources: (incrementalSources: IncrementalSource[]) => ({ incrementalSources }),
    }),
    reducers(() => ({
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
                isPlaying: false as boolean,
                isBuffering: false as boolean,
                lastTimestamp: null as number | null,
                watchTime: 0,
                bufferTime: 0,
            },
            {
                startBuffer: (state) => {
                    return {
                        isPlaying: false,
                        isBuffering: true,
                        lastTimestamp:
                            (state.isBuffering ? state.lastTimestamp : performance.now()) || performance.now(),
                        watchTime: state.watchTime,
                        bufferTime: state.bufferTime,
                    }
                },
                stopBuffer: (state) => {
                    return {
                        isPlaying: state.isPlaying,
                        isBuffering: false,
                        lastTimestamp: null,
                        watchTime: state.watchTime,
                        bufferTime:
                            state.lastTimestamp !== null
                                ? state.bufferTime + (performance.now() - state.lastTimestamp)
                                : state.bufferTime,
                    }
                },
                setPlay: (state) => {
                    return {
                        isPlaying: true,
                        isBuffering: false,
                        // if we are already playing then we carry the last timestamp over, otherwise we start from now
                        lastTimestamp: (state.isPlaying ? state.lastTimestamp : performance.now()) || performance.now(),
                        watchTime: state.watchTime,
                        bufferTime: state.bufferTime,
                    }
                },
                setPause: (state) => {
                    return {
                        isPlaying: false,
                        isBuffering: state.isBuffering,
                        lastTimestamp: null,
                        watchTime:
                            state.lastTimestamp !== null
                                ? state.watchTime + (performance.now() - state.lastTimestamp)
                                : state.watchTime,
                        bufferTime: state.bufferTime,
                    }
                },
                setEndReached: (state, { reached }) => {
                    if (!reached) {
                        return state
                    }

                    return {
                        isPlaying: false,
                        isBuffering: state.isBuffering,
                        lastTimestamp: null,
                        watchTime:
                            state.lastTimestamp !== null
                                ? state.watchTime + (performance.now() - state.lastTimestamp)
                                : state.watchTime,
                        bufferTime: state.bufferTime,
                    }
                },
                setErrorPlayerState: (state, { show }) => {
                    if (!show) {
                        return state
                    }
                    return {
                        isPlaying: state.isPlaying,
                        isBuffering: state.isBuffering,
                        lastTimestamp: null,
                        watchTime:
                            state.lastTimestamp !== null
                                ? state.watchTime + (performance.now() - state.lastTimestamp)
                                : state.watchTime,
                        bufferTime: state.bufferTime,
                    }
                },
                seekToTime: (state) => {
                    return {
                        ...state,
                        lastTimestamp:
                            state.isPlaying && state.lastTimestamp === null ? performance.now() : state.lastTimestamp,
                    }
                },
            },
        ],
        isBuffering: [true, { startBuffer: () => true, endBuffer: () => false }],
        isErrored: [false, { setErrorPlayerState: (_, { show }) => show }],
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
        messageTooLargeWarningSeen: [
            null as string | null,
            {
                reportMessageTooLargeWarningSeen: (_, { sessionRecordingId }) => sessionRecordingId,
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
    })),
    selectors({
        // Prop references for use by other logics
        sessionRecordingId: [() => [(_, props) => props], (props): string => props.sessionRecordingId],
        logicProps: [() => [(_, props) => props], (props): SessionRecordingPlayerLogicProps => props],
        playlistLogic: [() => [(_, props) => props], (props) => props.playlistLogic],

        roughAnimationFPS: [(s) => [s.playerSpeed], (playerSpeed) => playerSpeed * (1000 / 60)],
        currentPlayerState: [
            (s) => [
                s.playingState,
                s.isBuffering,
                s.isErrored,
                s.isScrubbing,
                s.isSkippingInactivity,
                s.snapshotsLoaded,
                s.snapshotsLoading,
            ],
            (
                playingState,
                isBuffering,
                isErrored,
                isScrubbing,
                isSkippingInactivity,
                snapshotsLoaded,
                snapshotsLoading
            ) => {
                switch (true) {
                    case isScrubbing:
                        // If scrubbing, playingState takes precedence
                        return playingState
                    case !snapshotsLoaded && !snapshotsLoading:
                        return SessionPlayerState.READY
                    case isErrored:
                        return SessionPlayerState.ERROR
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
            (sessionPlayerData) => {
                return (timestamp?: number): RecordingSegment | null => {
                    if (timestamp === undefined) {
                        return null
                    }
                    for (const segment of sessionPlayerData.segments) {
                        if (segment.startTimestamp <= timestamp && segment.endTimestamp >= timestamp) {
                            return segment
                        }
                    }
                    return null
                }
            },
        ],

        messageTooLargeWarnings: [
            (s) => [s.customRRWebEvents],
            (customRRWebEvents: customEvent[]) => {
                return customRRWebEvents.filter((event) => event.data.tag === 'Message too large')
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
    }),
    listeners(({ props, values, actions, cache }) => ({
        playerErrorSeen: ({ error }) => {
            const fingerprint = encodeURIComponent(error.message + error.filename + error.lineno + error.colno)
            if (values.reportedReplayerErrors.has(fingerprint)) {
                return
            }
            const extra = { fingerprint, playbackSessionId: values.sessionRecordingId }
            captureException(error, {
                extra,
                tags: { feature: 'replayer error swallowed' },
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

            cache.debug?.('tryInitReplayer', {
                windowId,
                rootFrame: values.rootFrame,
                snapshots: values.sessionPlayerData.snapshotsByWindowId[windowId],
            })

            const config: Partial<playerConfig> & { onError: (error: any) => void } = {
                root: values.rootFrame,
                ...COMMON_REPLAYER_CONFIG,
                // these two settings are attempts to improve performance of running two Replayers at once
                // the main player and a preview player
                mouseTail: values.showMouseTail && props.mode !== SessionRecordingPlayerMode.Preview,
                useVirtualDom: false,
                plugins,
                onError: (error) => {
                    actions.playerErrorSeen(error)
                },
            }
            const replayer = new Replayer(values.sessionPlayerData.snapshotsByWindowId[windowId], config)

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
            actions.reportRecordingPlayerSkipInactivityToggled(skipInactivitySetting)
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
                    if (searchParams.timestamp) {
                        const desiredStartTime = Number(searchParams.timestamp)
                        actions.seekToTimestamp(desiredStartTime, true)
                    } else if (searchParams.t) {
                        const desiredStartTime = Number(searchParams.t) * 1000
                        actions.seekToTime(desiredStartTime)
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
                actions.setErrorPlayerState(true)
            }
        },
        loadSnapshotSourcesFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                console.error('PostHog Recording Playback Error: No snapshots loaded')
                actions.setErrorPlayerState(true)
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
        setPause: () => {
            actions.stopAnimation()
            actions.pauseIframePlayback()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change
            values.player?.replayer?.pause()

            cache.debug?.('pause', {
                currentTimestamp: values.currentTimestamp,
                currentSegment: values.currentSegment,
            })
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
        setErrorPlayerState: ({ show }) => {
            if (show) {
                actions.incrementErrorCount()
                actions.stopAnimation()
            }
        },
        startScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            actions.reportRecordingPlayerSpeedChanged(speed)
            actions.syncPlayerSpeed()
        },
        seekToTimestamp: ({ timestamp, forcePlay }, breakpoint) => {
            actions.stopAnimation()
            cache.pausedMediaElements = []
            actions.setCurrentTimestamp(timestamp)

            // Check if we're seeking to a new segment
            const segment = values.segmentForTimestamp(timestamp)

            if (segment && segment !== values.currentSegment) {
                actions.setCurrentSegment(segment)
            }

            if (!values.snapshotsLoaded) {
                // We haven't started properly loading, or we're still polling so nothing to do
            } else if (!values.isRealtimePolling && !values.snapshotsLoading && segment?.kind === 'buffer') {
                // If not currently loading anything,
                // and part of the recording hasn't loaded, set error state
                values.player?.replayer?.pause()
                actions.endBuffer()
                console.error("Error: Player tried to seek to a position that hasn't loaded yet")
                actions.setErrorPlayerState(true)
            }

            // If next time is greater than last buffered time, set to buffering
            else if (segment?.kind === 'buffer') {
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                // NOTE: when we show a preview pane, this branch runs
                // in very large recordings this call to pause
                // can consume 100% CPU and freeze the entire page
                values.player?.replayer?.pause(values.toRRWebPlayerTime(timestamp))
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(values.toRRWebPlayerTime(timestamp))
                actions.updateAnimation()
                actions.endBuffer()
                actions.setErrorPlayerState(false)
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
                    cache.debug?.('gap segment: skipping forward')
                    newTimestamp = values.currentTimestamp + values.roughAnimationFPS
                }
            }

            // If we're beyond buffered position, set to buffering
            if (values.currentSegment?.kind === 'buffer') {
                // Pause only the animation, not our player, so it will restart
                // when the buffering progresses
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
                cache.debug('buffering')
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
                    cache.debug('end of recording reached', {
                        newTimestamp,
                        segments: values.sessionPlayerData.segments,
                        currentSegment: values.currentSegment,
                        nextSegment,
                        segmentIndex: values.sessionPlayerData.segments.indexOf(values.currentSegment),
                    })
                    // At the end of the recording. Pause the player and set fully to the end
                    actions.setEndReached()
                }
                return
            }

            // The normal loop. Progress the player position and continue the loop
            actions.setCurrentTimestamp(newTimestamp)
            cache.timer = requestAnimationFrame(actions.updateAnimation)
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },
        pauseIframePlayback: () => {
            const iframe = values.rootFrame?.querySelector('iframe')
            const iframeDocument = iframe?.contentWindow?.document
            if (!iframeDocument) {
                return
            }

            const audioElements = Array.from(iframeDocument.getElementsByTagName('audio'))
            const videoElements = Array.from(iframeDocument.getElementsByTagName('video'))
            const mediaElements: HTMLMediaElement[] = [...audioElements, ...videoElements]
            const playingElements = mediaElements.filter(isMediaElementPlaying)

            playingElements.forEach((el) => el.pause())
            cache.pausedMediaElements = values.endReached ? [] : playingElements
        },
        restartIframePlayback: () => {
            cache.pausedMediaElements.forEach((el: HTMLMediaElement) => el.play())
            cache.pausedMediaElements = []
        },

        exportRecordingToFile: async ({ exportUntransformedMobileData }) => {
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

                const payload = values.createExportJSON(!!exportUntransformedMobileData)

                const recordingFile = new File(
                    [JSON.stringify(payload, null, 2)],
                    `export-${props.sessionRecordingId}.${
                        exportUntransformedMobileData ? 'mobile.' : ''
                    }ph-recording.json`,
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

        reportMessageTooLargeWarningSeen: async ({ sessionRecordingId }) => {
            posthog.capture('message too large warning seen', { sessionRecordingId })
        },
    })),

    subscriptions(({ actions, values, props }) => ({
        sessionPlayerData: (next, prev) => {
            const hasSnapshotChanges = next?.snapshotsByWindowId !== prev?.snapshotsByWindowId

            // TODO: Detect if the order of the current window has changed (this would require re-initializing the player)

            if (hasSnapshotChanges) {
                actions.syncSnapshotsWithPlayer()
            }
        },
        timestampChangeTracking: (next) => {
            if (next.timestampMatchesPrevious < 10) {
                return
            }

            const rrwebPlayerTime = values.player?.replayer?.getCurrentTime()

            if (rrwebPlayerTime !== undefined && values.currentPlayerState === SessionPlayerState.PLAY) {
                actions.skipPlayerForward(rrwebPlayerTime, values.roughAnimationFPS)
            }
        },
        messageTooLargeWarnings: (next) => {
            if (
                values.messageTooLargeWarningSeen !== values.sessionRecordingId &&
                next.length > 0 &&
                props.mode !== SessionRecordingPlayerMode.Preview
            ) {
                actions.reportMessageTooLargeWarningSeen(values.sessionRecordingId)
            }
        },
    })),

    beforeUnmount(({ values, actions, cache, props }) => {
        if (props.mode === SessionRecordingPlayerMode.Preview) {
            values.player?.replayer?.destroy()
            return
        }

        delete (window as any).__debug_player

        actions.stopAnimation()

        cache.hasInitialized = false
        document.removeEventListener('fullscreenchange', cache.fullScreenListener)
        cache.pausedMediaElements = []
        values.player?.replayer?.destroy()
        actions.setPlayer(null)
        cache.unmountConsoleWarns?.()

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

    afterMount(({ props, actions, cache, values }) => {
        cache.debugging = localStorage.getItem('ph_debug_player') === 'true'
        cache.debug = (...args: any[]) => {
            if (cache.debugging) {
                // eslint-disable-next-line no-console
                console.log('[⏯️ PostHog Replayer]', ...args)
            }
        }
        ;(window as any).__debug_player = () => {
            cache.debugging = !cache.debugging
            localStorage.setItem('ph_debug_player', JSON.stringify(cache.debugging))
            cache.debug('player data', values.sessionPlayerData)
        }

        if (props.mode === SessionRecordingPlayerMode.Preview) {
            return
        }

        cache.pausedMediaElements = []
        cache.fullScreenListener = () => {
            actions.setIsFullScreen(document.fullscreenElement !== null)
        }

        document.addEventListener('fullscreenchange', cache.fullScreenListener)

        if (props.sessionRecordingId) {
            actions.maybeLoadRecordingMeta()
        }

        cache.openTime = performance.now()

        cache.unmountConsoleWarns = manageConsoleWarns(cache, actions.incrementWarningCount)
    }),
])

export const getCurrentPlayerTime = (logicProps: SessionRecordingPlayerLogicProps): number => {
    // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
    const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
    return Math.floor(playerTime / 1000)
}

export const manageConsoleWarns = (cache: any, onIncrement: (count: number) => void): (() => void) => {
    // NOTE: RRWeb can log _alot_ of warnings, so we debounce the count otherwise we just end up making the performance worse
    // We also don't log the warnings directly. Sometimes the sheer size of messages and warnings can cause the browser to crash deserializing it all
    ;(window as any).__posthog_player_warnings = []
    const warnings: any[][] = (window as any).__posthog_player_warnings

    let counter = 0

    let consoleWarnDebounceTimer: NodeJS.Timeout | null = null

    const actualConsoleWarn = console.warn

    const debouncedCounter = (args: any[]): void => {
        warnings.push(args)
        counter += 1

        if (!consoleWarnDebounceTimer) {
            consoleWarnDebounceTimer = setTimeout(() => {
                consoleWarnDebounceTimer = null
                onIncrement(warnings.length)

                actualConsoleWarn(
                    `[PostHog Replayer] ${counter} warnings (window.__posthog_player_warnings to safely log them)`
                )
                counter = 0
            }, 1000)
        }
    }

    const resetConsoleWarn = wrapConsole('warn', (args) => {
        if (typeof args[0] === 'string' && args[0].includes('[replayer]')) {
            debouncedCounter(args)
            // WARNING: Logging these out can cause the browser to completely crash, so we want to delay it and
            return false
        }

        return true
    })

    return () => {
        resetConsoleWarn()
        clearTimeout(cache.consoleWarnDebounceTimer)
    }
}
