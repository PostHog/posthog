import { KeyboardEvent } from 'react'
import { actions, connect, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'
import * as Sentry from '@sentry/react'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    PlayerPosition,
    RecordingSegment,
    SessionPlayerState,
    SessionRecordingPlayerProps,
    SessionRecordingType,
} from '~/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import {
    comparePlayerPositions,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
} from './playerUtils'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import equal from 'fast-deep-equal'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]
export const ONE_FRAME_MS = 100 // We don't really have frames but this feels granular enough

export interface Player {
    replayer: Replayer
    windowId: string
}

export interface SessionRecordingPlayerLogicProps extends SessionRecordingPlayerProps {
    recordingStartTime?: string
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect(({ sessionRecordingId, playerKey, recordingStartTime }: SessionRecordingPlayerLogicProps) => ({
        logic: [eventUsageLogic],
        values: [
            sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }),
            [
                'sessionRecordingId',
                'sessionPlayerData',
                'sessionPlayerSnapshotDataLoading',
                'loadMetaTimeMs',
                'loadFirstSnapshotTimeMs',
                'loadAllSnapshotsTimeMs',
            ],
            sharedListLogic({ sessionRecordingId, playerKey }),
            ['tab'],
            playerSettingsLogic,
            ['speed', 'skipInactivitySetting', 'isFullScreen'],
        ],
        actions: [
            sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }),
            ['loadRecordingSnapshotsSuccess', 'loadRecordingSnapshotsFailure', 'loadRecordingMetaSuccess'],
            sharedListLogic({ sessionRecordingId, playerKey }),
            ['setTab'],
            playerSettingsLogic,
            ['setSpeed', 'setSkipInactivitySetting', 'setIsFullScreen'],
        ],
    })),
    propsChanged(({ actions, props: { matching } }, { matching: oldMatching }) => {
        // Ensures that if filter results change, then matching results in this player logic will also change
        if (!equal(matching, oldMatching)) {
            actions.setMatching(matching)
        }
    }),
    actions({
        tryInitReplayer: () => true,
        setPlayer: (player: Player | null) => ({ player }),
        setPlay: true,
        setPause: true,
        startBuffer: true,
        endBuffer: true,
        startScrub: true,
        endScrub: true,
        setErrorPlayerState: (show: boolean) => ({ show }),
        setSkippingInactivity: (isSkippingInactivity: boolean) => ({ isSkippingInactivity }),
        syncPlayerSpeed: true,
        setCurrentPlayerPosition: (playerPosition: PlayerPosition | null) => ({ playerPosition }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seek: (playerPosition: PlayerPosition | null, forcePlay: boolean = false) => ({ playerPosition, forcePlay }),
        seekForward: (amount?: number) => ({ amount }),
        seekBackward: (amount?: number) => ({ amount }),
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
        setCurrentSegment: (segment: RecordingSegment) => ({ segment }),
        setRootFrame: (frame: HTMLDivElement) => ({ frame }),
        checkBufferingCompleted: true,
        initializePlayerFromStart: true,
        handleKeyDown: (event: KeyboardEvent<HTMLDivElement>) => ({ event }),
        incrementErrorCount: true,
        incrementWarningCount: true,
        setMatching: (matching: SessionRecordingType['matching_events']) => ({ matching }),
    }),
    reducers(({ props }) => ({
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
        currentPlayerPosition: [
            null as PlayerPosition | null,
            {
                setCurrentPlayerPosition: (_, { playerPosition }) => playerPosition,
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
        isBuffering: [true, { startBuffer: () => true, endBuffer: () => false }],
        isErrored: [false, { setErrorPlayerState: (_, { show }) => show }],
        isScrubbing: [false, { startScrub: () => true, endScrub: () => false }],
        errorCount: [0, { incrementErrorCount: (prevErrorCount, {}) => prevErrorCount + 1 }],
        warningCount: [0, { incrementWarningCount: (prevWarningCount, {}) => prevWarningCount + 1 }],
        matching: [
            props.matching ?? ([] as SessionRecordingType['matching_events']),
            {
                setMatching: (_, { matching }) => matching,
            },
        ],
    })),
    selectors({
        currentPlayerState: [
            (selectors) => [
                selectors.playingState,
                selectors.isBuffering,
                selectors.isErrored,
                selectors.isScrubbing,
                selectors.isSkippingInactivity,
            ],
            (playingState, isBuffering, isErrored, isScrubbing, isSkippingInactivity) => {
                if (isScrubbing) {
                    // If scrubbing, playingState takes precedence
                    return playingState
                }
                if (isErrored) {
                    return SessionPlayerState.ERROR
                }
                if (isBuffering) {
                    return SessionPlayerState.BUFFER
                }
                if (isSkippingInactivity && playingState !== SessionPlayerState.PAUSE) {
                    return SessionPlayerState.SKIP
                }
                return playingState
            },
        ],
        currentPlayerTime: [
            (selectors) => [selectors.currentPlayerPosition, selectors.sessionPlayerData],
            (currentPlayerPosition, sessionPlayerData) => {
                if (sessionPlayerData?.metadata?.segments && currentPlayerPosition) {
                    return getPlayerTimeFromPlayerPosition(currentPlayerPosition, sessionPlayerData?.metadata?.segments)
                }
                return 0
            },
        ],
        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],
        matchingEvents: [
            (s) => [s.matching],
            (matching) => (matching ?? []).map((filterMatches) => filterMatches.events).flat(),
        ],
        isSmallPlayer: [
            (s) => [s.rootFrame, () => window.innerWidth],
            (rootFrame) => {
                return !!rootFrame?.parentElement && rootFrame.parentElement.clientWidth < getBreakpoint('sm')
            },
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        setRootFrame: () => {
            actions.tryInitReplayer()
        },
        tryInitReplayer: () => {
            // Tries to initialize a new player
            const windowId: string | null = values.currentPlayerPosition?.windowId ?? null
            actions.setPlayer(null)
            if (values.rootFrame) {
                values.rootFrame.innerHTML = '' // Clear the previously drawn frames
            }
            if (
                !values.rootFrame ||
                windowId === null ||
                !values.sessionPlayerData.snapshotsByWindowId[windowId] ||
                values.sessionPlayerData.snapshotsByWindowId[windowId].length < 2
            ) {
                actions.setPlayer(null)
                return
            }
            const replayer = new Replayer(values.sessionPlayerData.snapshotsByWindowId[windowId], {
                root: values.rootFrame,
                triggerFocus: false,
                insertStyleRules: [
                    `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
                ],
            })
            actions.setPlayer({ replayer, windowId })
        },
        setPlayer: ({ player }) => {
            if (player) {
                actions.seek(values.currentPlayerPosition)
                actions.syncPlayerSpeed()
            }
        },
        setCurrentSegment: ({ segment }) => {
            // Check if we should we skip this segment
            if (!segment.isActive && values.skipInactivitySetting) {
                actions.setSkippingInactivity(true)
            } else {
                actions.setSkippingInactivity(false)
            }

            // Check if the new segment is for a different window_id than the last one
            // If so, we need to re-initialize the player
            if (values.player && values.player.windowId !== segment.windowId) {
                values.player?.replayer?.pause()
                actions.tryInitReplayer()
            }
            actions.seek(values.currentPlayerPosition)
        },
        setSkipInactivitySetting: ({ skipInactivitySetting }) => {
            eventUsageLogic.actions.reportRecordingPlayerSkipInactivityToggled(skipInactivitySetting)
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
            if (values.isSkippingInactivity) {
                // Sets speed to skip section in max 1 second
                const secondsToSkip =
                    ((values.currentSegment?.endPlayerPosition?.time ?? 0) -
                        (values.currentPlayerPosition?.time ?? 0)) /
                    1000
                const skipSpeed = Math.max(50, secondsToSkip)
                values.player?.replayer?.setConfig({ speed: skipSpeed })
            } else {
                values.player?.replayer?.setConfig({ speed: values.speed })
            }
        },
        checkBufferingCompleted: () => {
            // If buffering has completed, resume last playing state
            if (
                values.currentPlayerPosition &&
                values.sessionPlayerData.bufferedTo &&
                values.currentPlayerState === SessionPlayerState.BUFFER &&
                comparePlayerPositions(
                    values.currentPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) < 0
            ) {
                actions.endBuffer()
                actions.seek(values.currentPlayerPosition)
            }
        },
        initializePlayerFromStart: () => {
            const initialSegment = values.sessionPlayerData?.metadata?.segments[0]
            if (initialSegment) {
                actions.setCurrentSegment(initialSegment)
                actions.setCurrentPlayerPosition(initialSegment.startPlayerPosition)
                if (!values.player) {
                    actions.tryInitReplayer()
                }
            }
        },
        loadRecordingMetaSuccess: async (_, breakpoint) => {
            // Once the recording metadata is loaded, we set the player to the
            // beginning and then try to play the recording
            actions.initializePlayerFromStart()
            actions.checkBufferingCompleted()
            breakpoint()
        },

        loadRecordingSnapshotsSuccess: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.player?.replayer?.service.state.context.events ?? []
            const eventsToAdd = []
            if (values.currentSegment?.windowId !== undefined) {
                eventsToAdd.push(
                    ...(values.sessionPlayerData.snapshotsByWindowId[values.currentSegment?.windowId] ?? []).slice(
                        currentEvents.length
                    )
                )
            }

            // If replayer isn't initialized, it will be initialized with the already loaded snapshots
            if (!!values.player?.replayer) {
                for (const event of eventsToAdd) {
                    await values.player?.replayer?.addEvent(event)
                }
            } else {
                actions.initializePlayerFromStart()
            }
            actions.checkBufferingCompleted()
            breakpoint()
        },

        loadRecordingSnapshotsFailure: () => {
            if (Object.keys(values.sessionPlayerData.snapshotsByWindowId).length === 0) {
                actions.setErrorPlayerState(true)
            }
        },
        setPlay: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change

            // Use the start of the current segment if there is no currentPlayerPosition
            // (theoretically, should never happen, but Typescript doesn't know that)
            let nextPlayerPosition = values.currentPlayerPosition || values.currentSegment?.startPlayerPosition

            if (values.currentSegment === values.sessionPlayerData.metadata.segments.slice(-1)[0]) {
                // If we're at the end of the recording, go back to the beginning
                nextPlayerPosition = values.sessionPlayerData.metadata.segments[0].startPlayerPosition
            }
            if (nextPlayerPosition) {
                actions.seek(nextPlayerPosition, true)
            }
        },
        setPause: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change
            values.player?.replayer?.pause()
        },
        startBuffer: () => {
            actions.stopAnimation()
        },
        setErrorPlayerState: ({ show }) => {
            if (show) {
                actions.stopAnimation()
            }
        },
        startScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            eventUsageLogic.actions.reportRecordingPlayerSpeedChanged(speed)
            actions.syncPlayerSpeed()
        },
        seek: async ({ playerPosition, forcePlay }, breakpoint) => {
            actions.stopAnimation()
            actions.setCurrentPlayerPosition(playerPosition)

            // Check if we're seeking to a new segment
            let nextSegment = null
            if (playerPosition && values.sessionPlayerData?.metadata) {
                nextSegment = getSegmentFromPlayerPosition(playerPosition, values.sessionPlayerData.metadata.segments)
                if (
                    nextSegment &&
                    (nextSegment.windowId !== values.currentSegment?.windowId ||
                        nextSegment.startTimeEpochMs !== values.currentSegment?.startTimeEpochMs)
                ) {
                    actions.setCurrentSegment(nextSegment)
                }
            }

            // If not currently loading anything and part of the recording hasn't loaded, set error state
            if (
                (!values.sessionPlayerSnapshotDataLoading && !values.sessionPlayerData.bufferedTo) ||
                (!values.sessionPlayerSnapshotDataLoading &&
                    !!values.sessionPlayerData?.bufferedTo &&
                    !!playerPosition &&
                    !!values.currentSegment &&
                    comparePlayerPositions(
                        playerPosition,
                        values.sessionPlayerData.bufferedTo,
                        values.sessionPlayerData.metadata.segments
                    ) > 0)
            ) {
                values.player?.replayer?.pause()
                actions.endBuffer()
                actions.setErrorPlayerState(true)
            }

            // If next time is greater than last buffered time, set to buffering
            else if (
                !values.sessionPlayerData?.bufferedTo ||
                !playerPosition ||
                !values.currentSegment ||
                comparePlayerPositions(
                    playerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0
            ) {
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.player?.replayer?.pause(playerPosition.time)
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(playerPosition.time)
                actions.updateAnimation()
                actions.endBuffer()
                actions.setErrorPlayerState(false)
            }
            breakpoint()
        },
        seekForward: ({ amount = values.jumpTimeMs }) => {
            if (!values.currentPlayerPosition) {
                return
            }
            const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                values.currentPlayerPosition,
                values.sessionPlayerData.metadata.segments
            )
            if (currentPlayerTime !== null) {
                const nextPlayerTime = currentPlayerTime + amount
                let nextPlayerPosition = getPlayerPositionFromPlayerTime(
                    nextPlayerTime,
                    values.sessionPlayerData.metadata.segments
                )
                if (!nextPlayerPosition) {
                    // At the end of the recording. Pause the player and set to the end of the recording
                    actions.setPause()
                    nextPlayerPosition = values.sessionPlayerData.metadata.segments.slice(-1)[0].endPlayerPosition
                }
                actions.seek(nextPlayerPosition)
            }
        },
        seekBackward: ({ amount = values.jumpTimeMs }) => {
            if (!values.currentPlayerPosition) {
                return
            }

            const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                values.currentPlayerPosition,
                values.sessionPlayerData.metadata.segments
            )
            if (currentPlayerTime !== null) {
                const nextPlayerTime = Math.max(currentPlayerTime - amount, 0)
                const nextPlayerPosition = getPlayerPositionFromPlayerTime(
                    nextPlayerTime,
                    values.sessionPlayerData.metadata.segments
                )

                actions.seek(nextPlayerPosition)
            }
        },

        togglePlayPause: () => {
            // If buffering, toggle is a noop
            if (values.currentPlayerState === SessionPlayerState.BUFFER) {
                return
            }
            // If paused, start playing
            if (values.currentPlayerState === SessionPlayerState.PAUSE) {
                actions.setPlay()
            }
            // If playing, pause
            else {
                actions.setPause()
            }
        },
        updateAnimation: () => {
            // The main loop of the player. Called on each frame
            const playerTime = values.player?.replayer?.getCurrentTime()
            let nextPlayerPosition: PlayerPosition | null = null
            if (playerTime !== undefined && values.currentSegment) {
                nextPlayerPosition = {
                    windowId: values.currentSegment.windowId,
                    // Cap the player position to the end of the segment. Below, we'll check if
                    // the player is at the end of the segment and if so, we'll go to the next one
                    time: Math.min(playerTime, values.currentSegment.endPlayerPosition.time),
                }
            }

            // If we're beyond the current segments, move to next segments if there is one
            if (
                nextPlayerPosition &&
                values.currentSegment?.endPlayerPosition &&
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.currentSegment?.endPlayerPosition,
                    values.sessionPlayerData.metadata.segments
                ) >= 0
            ) {
                const nextSegmentIndex = values.sessionPlayerData.metadata.segments.indexOf(values.currentSegment) + 1
                if (nextSegmentIndex < values.sessionPlayerData.metadata.segments.length) {
                    const nextSegment = values.sessionPlayerData.metadata.segments[nextSegmentIndex]
                    actions.setCurrentPlayerPosition(nextSegment.startPlayerPosition)
                    actions.setCurrentSegment(nextSegment)
                } else {
                    // At the end of the recording. Pause the player and set fully to the end
                    actions.setPause()
                }
            }
            // If next position tries to access snapshot that is not loaded, show error state
            else if (
                !!values.sessionPlayerData?.bufferedTo &&
                !!nextPlayerPosition &&
                !!values.currentSegment &&
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0 &&
                !values.sessionPlayerSnapshotDataLoading
            ) {
                values.player?.replayer?.pause()
                actions.endBuffer()
                actions.setErrorPlayerState(true)
            }

            // If we're beyond buffered position, set to buffering
            else if (
                !values.sessionPlayerData.bufferedTo ||
                !nextPlayerPosition ||
                !values.currentSegment ||
                comparePlayerPositions(
                    nextPlayerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0
            ) {
                // Pause only the animation, not our player, so it will restart
                // when the buffering progresses
                values.player?.replayer?.pause()
                actions.startBuffer()
                actions.setErrorPlayerState(false)
            } else {
                // The normal loop. Progress the player position and continue the loop
                actions.setCurrentPlayerPosition(nextPlayerPosition)
                cache.timer = requestAnimationFrame(actions.updateAnimation)
            }
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },
        handleKeyDown: ({ event }) => {
            // Don't trigger keydown evens if in input box
            if ((event.target as HTMLInputElement)?.matches('input')) {
                return
            }
            if (event.key === ' ') {
                actions.togglePlayPause()
                event.preventDefault()
            } else if (event.key === 'ArrowLeft') {
                // If alt key is pressed we pause the video as otherwise moving by one frame makes no sense
                event.altKey && actions.setPause()
                actions.seekBackward(event.altKey ? ONE_FRAME_MS : undefined)
                event.preventDefault()
            } else if (event.key === 'ArrowRight') {
                event.altKey && actions.setPause()
                actions.seekForward(event.altKey ? ONE_FRAME_MS : undefined)
                event.preventDefault()
            } else {
                // Playback speeds shortcuts
                for (let i = 0; i < PLAYBACK_SPEEDS.length; i++) {
                    if (event.key === (i + 1).toString()) {
                        actions.setSpeed(PLAYBACK_SPEEDS[i])
                    }
                }
            }
        },
    })),
    windowValues({
        isSmallScreen: (window: any) => window.innerWidth < getBreakpoint('md'),
    }),
    events(({ values, actions, cache }) => ({
        beforeUnmount: () => {
            values.player?.replayer?.pause()
            actions.setPlayer(null)
            if (cache.originalWarning) {
                console.warn = cache.originalWarning
            }
            if (cache.errorHandler) {
                window.removeEventListener('error', cache.errorHandler)
            }
            eventUsageLogic.actions.reportRecordingViewedSummary({
                viewed_time_ms: cache.openTime !== undefined ? performance.now() - cache.openTime : undefined,
                recording_duration_ms: values.sessionPlayerData?.metadata
                    ? values.sessionPlayerData.metadata.recordingDurationMs
                    : undefined,
                recording_age_days:
                    values.sessionPlayerData?.metadata && values.sessionPlayerData?.metadata.segments.length > 0
                        ? Math.floor(
                              (Date.now() - values.sessionPlayerData.metadata.segments[0].startTimeEpochMs) /
                                  (1000 * 60 * 60 * 24)
                          )
                        : undefined,
                meta_data_load_time_ms: values.loadMetaTimeMs ?? undefined,
                first_snapshot_load_time_ms: values.loadFirstSnapshotTimeMs ?? undefined,
                first_snapshot_and_meta_load_time_ms:
                    values.loadFirstSnapshotTimeMs !== null && values.loadMetaTimeMs !== null
                        ? Math.max(values.loadFirstSnapshotTimeMs, values.loadMetaTimeMs)
                        : undefined,
                all_snapshots_load_time_ms: values.loadAllSnapshotsTimeMs ?? undefined,
                rrweb_warning_count: values.warningCount,
                error_count_during_recording_playback: values.errorCount,
            })
        },
        afterMount: () => {
            cache.openTime = performance.now()

            cache.errorHandler = (error: ErrorEvent) => {
                Sentry.captureException(error)
                actions.incrementErrorCount()
            }
            window.addEventListener('error', cache.errorHandler)
            cache.originalWarning = console.warn
            console.warn = function (...args: Array<unknown>) {
                if (typeof args[0] === 'string' && args[0].includes('[replayer]')) {
                    actions.incrementWarningCount()
                }
                cache.originalWarning(...args)
            }
        },
    })),
])
