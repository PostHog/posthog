import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SessionPlayerState, SessionPlayerTime } from '~/types'
import { eventWithTime, playerMetaData } from 'rrweb/typings/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]

const BUFFER_TIME_BUFFER_MS = 5 * 1000 // The length of time player has to have loaded to get out of buffering state

export function getZeroOffsetTime(time: number, meta: playerMetaData): number {
    return Math.max(Math.min(time - meta.startTime, meta.totalTime), 0)
}
export function getOffsetTime(zeroOffsetTime: number, meta: playerMetaData): number {
    return Math.max(Math.min(zeroOffsetTime + meta.startTime, meta.endTime), meta.startTime)
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [
            sessionRecordingLogic,
            ['sessionRecordingId', 'sessionPlayerData', 'sessionPlayerDataLoading', 'isPlayable'],
        ],
        actions: [sessionRecordingLogic, ['loadRecordingSnapshotsSuccess', 'loadRecordingMetaSuccess']],
    },
    actions: {
        initReplayer: (frame: HTMLDivElement) => ({ frame }),
        setReplayer: (replayer: Replayer) => ({ replayer }),
        setPlay: true,
        setPause: true,
        setBuffer: true,
        setSkip: true,
        setScrub: true,
        setMeta: (meta: playerMetaData) => ({ meta }),
        setMetaDuration: (duration: number) => ({ duration }),
        setCurrentTime: (time: number) => ({ time }),
        setRealTime: (time: number) => ({ time }),
        setLastBufferedTime: (time: number) => ({ time }),
        setSpeed: (speed: number) => ({ speed }),
        togglePlayPause: true,
        seek: (time: number, forcePlay: boolean = false) => ({ time, forcePlay }),
        seekForward: true,
        seekBackward: true,
        clearLoadingState: true,
        resolvePlayerState: true,
        updateAnimation: true,
        stopAnimation: true,
    },
    reducers: () => ({
        replayer: [
            null as Replayer | null,
            {
                setReplayer: (_, { replayer }) => replayer,
            },
        ],
        time: [
            {
                current: 0,
                lastBuffered: 0,
            } as SessionPlayerTime,
            {
                setCurrentTime: (state, { time }) => ({ ...state, current: time }),
                setLastBufferedTime: (state, { time }) => ({ ...state, lastBuffered: time }),
            },
        ],
        realTime: [
            {
                current: 0,
                lastBuffered: 0,
            } as SessionPlayerTime,
            {
                seek: (state, { time }) => ({ ...state, current: time }),
                setCurrentTime: (state, { time }) => ({ ...state, current: time }),
                setRealTime: (state, { time }) => ({ ...state, current: time }),
            },
        ],
        speed: [
            1,
            {
                setSpeed: (_, { speed }) => speed,
            },
        ],
        meta: [
            {
                startTime: 0,
                endTime: 0,
                totalTime: 0,
            } as playerMetaData,
            {
                setMeta: (_, { meta }) => meta,
                setMetaDuration: (state, { duration }) => ({ ...state, endTime: duration, totalTime: duration }),
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
        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],
        snapshots: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => sessionPlayerData?.snapshots ?? [],
        ],
        zeroOffsetTime: [
            (selectors) => [selectors.time, selectors.realTime, selectors.meta],
            (time, realTime, meta) => ({
                current: getZeroOffsetTime(realTime.current, meta),
                lastBuffered: getZeroOffsetTime(time.lastBuffered, meta),
            }),
        ],
    },
    listeners: ({ values, actions, cache }) => ({
        initReplayer: ({ frame }) => {
            if (values.snapshots.length < 2) {
                return
            }

            const replayer = new Replayer(values.snapshots, {
                root: frame.current,
                skipInactive: true,
                triggerFocus: false,
                speed: values.speed,
            })
            replayer.on('finish', () => {
                // Use 500ms buffer because current time is not always exactly identical to end time.
                if (values.time.current + 500 >= values.meta.endTime) {
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

            actions.setReplayer(replayer)
        },
        setReplayer: () => {
            actions.setPlay()
        },
        loadRecordingMetaSuccess: async ({ sessionPlayerData }, breakpoint) => {
            // Set meta timestamps when first chunk loads. The first time is a guesstimate that's later corrected by
            // the time the whole chunk loads.
            const startOffset = sessionPlayerData?.session_recording?.start_time ?? 0
            const duration = sessionPlayerData?.session_recording?.recording_duration ?? 0
            actions.setMeta({
                startTime: startOffset,
                endTime: startOffset + duration,
                totalTime: duration,
            })

            breakpoint()
        },
        loadRecordingSnapshotsSuccess: async (_, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.replayer?.service.state.context.events ?? []
            const eventsToAdd = values.snapshots.slice(currentEvents.length) ?? []

            if (eventsToAdd.length < 1) {
                return
            }

            // If replayer isn't initialized, it will be initialized with the already loaded snapshots
            if (!!values.replayer) {
                eventsToAdd.forEach((event: eventWithTime) => {
                    values.replayer?.addEvent(event)
                })
            }

            // Update last buffered point
            const lastEvent = eventsToAdd[eventsToAdd.length - 1]
            actions.setLastBufferedTime(lastEvent.timestamp)

            // If buffering has completed, resume last playing state
            if (
                values.currentPlayerState === SessionPlayerState.BUFFER &&
                values.time.current + BUFFER_TIME_BUFFER_MS < lastEvent.timestamp
            ) {
                actions.clearLoadingState()
                actions.setPlay()
            }

            // Set meta once whole session recording loads. This overrides the meta set when metadata
            // was fetched separately.
            if (!values.sessionPlayerDataLoading && !!values.replayer) {
                const meta = values.replayer.getMetaData()
                // Sometimes replayer doesn't update with events we recently added.
                const endTime = Math.max(
                    meta.endTime,
                    eventsToAdd.length ? eventsToAdd[eventsToAdd.length - 1]?.timestamp : 0
                )
                const finalMeta = {
                    ...meta,
                    endTime,
                    totalTime: endTime - meta.startTime,
                }
                actions.setMeta(finalMeta)
            }

            breakpoint()
        },
        setPlay: () => {
            actions.stopAnimation()
            values.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
            actions.seek(values.time.current, true)
        },
        setPause: () => {
            actions.stopAnimation()
            values.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
            values.replayer?.pause()
        },
        setBuffer: () => {
            actions.stopAnimation()
        },
        setScrub: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            values.replayer?.setConfig({ speed })
        },
        seek: async ({ time, forcePlay }, breakpoint) => {
            // Real seeking is debounced so as not to overload rrweb.
            await breakpoint(100)

            // Time passed into seek function must be timestamp offset time.
            const nextTime = getZeroOffsetTime(time ?? 0, values.meta)

            // Set current time to keep player updated. Replayer will catch up once time is buffered
            actions.setCurrentTime(time ?? 0)

            // If next time is greater than last buffered time, set to buffering
            if (nextTime > values.zeroOffsetTime.lastBuffered) {
                values.replayer?.pause()
                actions.setBuffer()
            }
            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.replayer?.pause(nextTime)
                actions.clearLoadingState()
            }
            // Otherwise play
            else {
                values.replayer?.play(nextTime)
                actions.updateAnimation()
            }

            breakpoint()
        },
        seekForward: () => {
            actions.seek(values.time.current + values.jumpTimeMs)
        },
        seekBackward: () => {
            actions.seek(values.time.current - values.jumpTimeMs)
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
            const nextTime = getOffsetTime(values.replayer?.getCurrentTime() || 0, values.meta)
            if (nextTime > values.time.lastBuffered) {
                values.replayer?.pause()
                actions.setBuffer()
            } else {
                actions.setCurrentTime(nextTime)
            }
            cache.timer = requestAnimationFrame(actions.updateAnimation)
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },
        clearLoadingState: () => {
            values.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
        },
    }),
    windowValues: {
        isSmallScreen: (window) => window.innerWidth < getBreakpoint('md'),
    },
})
