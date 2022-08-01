import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { windowValues } from 'kea-window-values'
import type { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { PlayerPosition, RecordingSegment, SessionPlayerState } from '~/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import {
    comparePlayerPositions,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
} from './playerUtils'
import React from 'react'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]

export interface Player {
    replayer: Replayer
    windowId: string
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic']),
    connect({
        logic: [eventUsageLogic],
        values: [sessionRecordingLogic, ['sessionRecordingId', 'sessionPlayerData']],
        actions: [sessionRecordingLogic, ['loadRecordingSnapshotsSuccess', 'loadRecordingMetaSuccess']],
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
        setSkipInactivitySetting: (skipInactivitySetting: boolean) => ({ skipInactivitySetting }),
        setSkippingInactivity: (isSkippingInactivity: boolean) => ({ isSkippingInactivity }),
        syncPlayerSpeed: true,
        setCurrentPlayerPosition: (playerPosition: PlayerPosition | null) => ({ playerPosition }),
        setSpeed: (speed: number) => ({ speed }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seek: (playerPosition: PlayerPosition | null, forcePlay: boolean = false) => ({ playerPosition, forcePlay }),
        seekForward: true,
        seekBackward: true,
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
        setCurrentSegment: (segment: RecordingSegment) => ({ segment }),
        setRootFrame: (frame: HTMLDivElement) => ({ frame }),
        checkBufferingCompleted: true,
        initializePlayerFromStart: true,
        handleKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => ({ event }),
    }),
    reducers(() => ({
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
        speed: [
            1,
            { persist: true },
            {
                setSpeed: (_, { speed }) => speed,
            },
        ],
        skipInactivitySetting: [
            true,
            { persist: true },
            {
                setSkipInactivitySetting: (_, { skipInactivitySetting }) => skipInactivitySetting,
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
        isScrubbing: [false, { startScrub: () => true, endScrub: () => false }],
    })),
    selectors({
        currentPlayerState: [
            (selectors) => [
                selectors.playingState,
                selectors.isBuffering,
                selectors.isScrubbing,
                selectors.isSkippingInactivity,
            ],
            (playingState, isBuffering, isScrubbing, isSkippingInactivity) => {
                if (isScrubbing) {
                    // If scrubbing, playingState takes precedence
                    return playingState
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
        setPlay: () => {
            actions.stopAnimation()
            actions.syncPlayerSpeed() // hotfix: speed changes on player state change

            // Use the start of the current segment if there is no currentPlayerPosition
            // (theoretically, should never happen, but Typescript doesn't know that)
            const nextPlayerPosition = values.currentPlayerPosition || values.currentSegment?.startPlayerPosition
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

            // If next time is greater than last buffered time, set to buffering
            if (
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
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.player?.replayer?.pause(playerPosition.time)
                actions.endBuffer()
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(playerPosition.time)
                actions.updateAnimation()
                actions.endBuffer()
            }
            breakpoint()
        },
        seekForward: () => {
            if (values.currentPlayerPosition) {
                const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                    values.currentPlayerPosition,
                    values.sessionPlayerData.metadata.segments
                )
                if (currentPlayerTime !== null) {
                    const nextPlayerTime = currentPlayerTime + values.jumpTimeMs
                    let nextPlayerPosition = getPlayerPositionFromPlayerTime(
                        nextPlayerTime,
                        values.sessionPlayerData.metadata.segments
                    )
                    if (!nextPlayerPosition) {
                        // At the end of the recording. Pause the player and reset the playerPosition
                        actions.setPause()
                        nextPlayerPosition = values.sessionPlayerData.metadata.segments[0].startPlayerPosition
                    }
                    actions.seek(nextPlayerPosition)
                }
            }
        },
        seekBackward: () => {
            if (values.currentPlayerPosition) {
                const currentPlayerTime = getPlayerTimeFromPlayerPosition(
                    values.currentPlayerPosition,
                    values.sessionPlayerData.metadata.segments
                )
                if (currentPlayerTime !== null) {
                    const nextPlayerTime = Math.max(currentPlayerTime - values.jumpTimeMs, 0)
                    const nextPlayerPosition = getPlayerPositionFromPlayerTime(
                        nextPlayerTime,
                        values.sessionPlayerData.metadata.segments
                    )
                    actions.seek(nextPlayerPosition)
                }
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
                    // At the end of the recording. Pause the player and reset the playerPosition
                    actions.setPause()
                    actions.setCurrentPlayerPosition(values.sessionPlayerData.metadata.segments[0].startPlayerPosition)
                }
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
                actions.seekBackward()
            } else if (event.key === 'ArrowRight') {
                actions.seekForward()
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
    events(({ values, actions }) => ({
        beforeUnmount: () => {
            values.player?.replayer?.pause()
            actions.setPlayer(null)
        },
    })),
])
