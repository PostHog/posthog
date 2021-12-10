import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { PlayerPosition, RecordingSegment, SessionPlayerState, SessionPlayerTime } from '~/types'
import { eventWithTime } from 'rrweb/typings/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import {
    comparePlayerPositions,
    getPlayerPositionFromPlayerTime,
    getPlayerTimeFromPlayerPosition,
    getSegmentFromPlayerPosition,
} from './playerUtils'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]

interface Player {
    replayer: Replayer
    windowId: string
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType<Player>>({
    path: ['scenes', 'session-recordings', 'player', 'sessionRecordingPlayerLogic'],
    connect: {
        logic: [eventUsageLogic],
        values: [sessionRecordingLogic, ['sessionRecordingId', 'sessionPlayerData']],
        actions: [sessionRecordingLogic, ['loadRecordingSnapshotsSuccess', 'loadRecordingMetaSuccess']],
    },
    actions: {
        tryInitReplayer: () => true,
        setPlayer: (player: Player | null) => ({ player }),
        setPlay: true,
        setPause: true,
        setBuffer: true,
        setSkip: true,
        setScrub: true,
        setCurrentPlayerPosition: (playerPosition: PlayerPosition | null) => ({ playerPosition }),
        setCurrentTime: (time: number) => ({ time }),
        setLastBufferedTime: (time: number) => ({ time }),
        setSpeed: (speed: number) => ({ speed }),
        setScale: (scale: number) => ({ scale }),
        togglePlayPause: true,
        seek: (playerPosition: PlayerPosition | null, forcePlay: boolean = false) => ({ playerPosition, forcePlay }),
        seekForward: true,
        seekBackward: true,
        clearLoadingState: true,
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
        setCurrentSegment: (segment: RecordingSegment) => ({ segment }),
        setRootFrame: (frame: HTMLDivElement) => ({ frame }),
    },
    reducers: () => ({
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
        time: [
            {
                current: 0,
                lastBuffered: 10000000,
            } as SessionPlayerTime,
            {
                setCurrentTime: (state, { time }) => ({ ...state, current: time }),
                setLastBufferedTime: (state, { time }) => ({ ...state, lastBuffered: time }),
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
            8,
            {
                setSpeed: (_, { speed }) => speed,
            },
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
        loadingState: [
            SessionPlayerState.BUFFER as
                | SessionPlayerState.BUFFER
                | SessionPlayerState.SKIP
                | SessionPlayerState.SCRUB
                | null,
            {
                setBuffer: () => SessionPlayerState.BUFFER,
                setSkip: () => SessionPlayerState.SKIP,
                setScrub: () => SessionPlayerState.SCRUB,
                clearLoadingState: () => null,
            },
        ],
    }),
    selectors: {
        currentPlayerState: [
            (selectors) => [selectors.playingState, selectors.loadingState],
            (playingState, loadingState) => {
                if (loadingState === SessionPlayerState.SCRUB) {
                    // If scrubbing, playingState takes precedence
                    return playingState
                }
                return loadingState ?? playingState
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
    },
    listeners: ({ values, actions, cache }) => ({
        setRootFrame: () => {
            actions.tryInitReplayer()
        },
        tryInitReplayer: () => {
            const windowId: string | null = values.currentPlayerPosition?.windowId ?? null
            console.log('tryInitReplayer', windowId)
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
                skipInactive: true,
                triggerFocus: false,
                speed: values.speed,
                insertStyleRules: [
                    `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
                ],
            })
            console.log('initReplayer', replayer)
            replayer.on('finish', () => {
                // Use 500ms buffer because current time is not always exactly identical to end time.
                if (values.time.current + 500 >= values.sessionPlayerData.metadata.endTime) {
                    actions.setPause()
                }
            })
            replayer.on('skip-start', () => {
                if (values.loadingState !== SessionPlayerState.BUFFER) {
                    actions.setSkip()
                }
            })
            replayer.on('skip-end', () => {
                if (values.loadingState === SessionPlayerState.SKIP) {
                    actions.clearLoadingState()
                }
            })
            actions.setPlayer({ replayer, windowId })
        },
        setPlayer: ({ player }) => {
            if (player) {
                actions.seek(values.currentPlayerPosition)
            }
        },
        setCurrentSegment: ({ segment }) => {
            console.log('setCurrentSegment', segment)
            if (values.player && values.player.windowId !== segment.windowId) {
                console.log('setCurrentSegment: windowId mismatch')
                values.player?.replayer?.pause()
                actions.setPlayer(null)
                values.rootFrame.innerHTML = '' // Clear the previously drawn frames
                actions.tryInitReplayer()
            }
            actions.seek(values.currentPlayerPosition)
        },
        loadRecordingMetaSuccess: async (_, breakpoint) => {
            actions.setCurrentSegment(values.sessionPlayerData.metadata.segments[0])
            actions.setCurrentPlayerPosition(values.sessionPlayerData.metadata.segments[0].startPlayerPosition)
            if (!values.player) {
                actions.tryInitReplayer()
            }
            breakpoint()
        },
        loadRecordingSnapshotsSuccess: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.player?.replayer?.service.state.context.events ?? []
            const eventsToAdd = []
            if (values.currentSegment?.windowId) {
                eventsToAdd.push(
                    ...(values.sessionPlayerData.snapshotsByWindowId[values.currentSegment?.windowId] ?? []).slice(
                        currentEvents.length
                    )
                )
            }

            // If replayer isn't initialized, it will be initialized with the already loaded snapshots
            if (!!values.player?.replayer) {
                eventsToAdd.forEach((event: eventWithTime) => {
                    values.player?.replayer?.addEvent(event)
                })
            } else {
                actions.tryInitReplayer()
            }

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
                actions.clearLoadingState()
                actions.setPlay()
            }

            breakpoint()
        },
        setPlay: () => {
            actions.stopAnimation()
            values.player?.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
            // Seek to currentPlayerPosition or start of the currentSegment
            console.log('setPlay', values.currentPlayerPosition, values.currentSegment?.startPlayerPosition)
            const nextPlayerPosition = values.currentPlayerPosition || values.currentSegment?.startPlayerPosition
            if (nextPlayerPosition) {
                actions.seek(nextPlayerPosition, true)
            }
        },
        setPause: () => {
            actions.stopAnimation()
            values.player?.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
            values.player?.replayer?.pause()
        },
        setBuffer: () => {
            actions.stopAnimation()
        },
        setScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            values.player?.replayer?.setConfig({ speed })
        },
        seek: async ({ playerPosition, forcePlay }, breakpoint) => {
            // Real seeking is debounced so as not to overload rrweb.
            await breakpoint(100)
            actions.stopAnimation()
            console.log('seek', playerPosition, forcePlay)

            actions.setCurrentPlayerPosition(playerPosition)

            // Check if we're seeking to a new segment
            let nextSegment = null
            if (playerPosition) {
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
                !values.sessionPlayerData.bufferedTo ||
                !playerPosition ||
                !values.currentSegment ||
                comparePlayerPositions(
                    playerPosition,
                    values.sessionPlayerData.bufferedTo,
                    values.sessionPlayerData.metadata.segments
                ) > 0
            ) {
                values.player?.replayer?.pause()
                actions.setBuffer()
            }

            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.player?.replayer?.pause(playerPosition.time)
                actions.clearLoadingState()
            }
            // Otherwise play
            else {
                values.player?.replayer?.play(playerPosition.time)
                actions.updateAnimation()
                actions.clearLoadingState()
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
                    const nextPlayerPosition = getPlayerPositionFromPlayerTime(
                        nextPlayerTime,
                        values.sessionPlayerData.metadata.segments
                    )
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
                    const nextPlayerTime = currentPlayerTime - values.jumpTimeMs
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
            // If skipping, pause and turn skipping off
            else if (values.currentPlayerState === SessionPlayerState.SKIP) {
                actions.clearLoadingState()
                actions.setPause()
            }
            // If playing, pause
            else {
                actions.setPause()
            }
        },
        updateAnimation: () => {
            const playerTime = values.player?.replayer?.getCurrentTime()
            let nextPlayerPosition: PlayerPosition | null = null
            if (playerTime !== undefined && values.currentSegment) {
                nextPlayerPosition = {
                    windowId: values.currentSegment.windowId,
                    time: Math.min(playerTime, values.currentSegment.endPlayerPosition.time),
                }
            }
            // console.log(playerTime, nextPlayerPosition?.time, values.sessionPlayerData.metadata.segments.indexOf(values.currentSegment))

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
                    actions.setCurrentPlayerPosition(nextPlayerPosition)
                    actions.setPause()
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
                values.player?.replayer?.pause()
                actions.setBuffer()
            } else {
                actions.setCurrentPlayerPosition(nextPlayerPosition)
                cache.timer = requestAnimationFrame(actions.updateAnimation)
            }
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },
        clearLoadingState: () => {
            values.player?.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
        },
    }),
    windowValues: {
        isSmallScreen: (window) => window.innerWidth < getBreakpoint('md'),
    },
    events: ({ values, actions }) => ({
        beforeUnmount: () => {
            values.player?.replayer?.pause()
            actions.setPlayer(null)
        },
    }),
})
