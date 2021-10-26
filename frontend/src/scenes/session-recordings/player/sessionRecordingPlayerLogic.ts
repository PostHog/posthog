import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SessionPlayerState, SessionPlayerTime } from '~/types'
import { eventWithTime, playerMetaData } from 'rrweb/typings/types'
import { sessionsPlayLogic } from 'scenes/sessions/sessionsPlayLogic'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]

const BUFFER_TIME_BUFFER_MS = 5 * 1000 // The length of time player has to have loaded to get out of buffering state

function getZeroOffsetTime(time: number, meta: playerMetaData): number {
    return Math.max(Math.min(time - meta.startTime, meta.totalTime), 0)
}
function getOffsetTime(zeroOffsetTime: number, meta: playerMetaData): number {
    return Math.max(Math.min(zeroOffsetTime + meta.startTime, meta.endTime), meta.startTime)
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [
            sessionsPlayLogic,
            ['sessionRecordingId', 'sessionPlayerData', 'sessionPlayerDataLoading', 'isPlayable', 'chunkIndex'],
        ],
        actions: [sessionsPlayLogic, ['loadRecordingSuccess']],
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
            replayer.on('finish', actions.setPause)
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
        loadRecordingSuccess: async ({ sessionPlayerData }, breakpoint) => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.replayer?.service.state.context.events ?? []
            const eventsToAdd = values.snapshots.slice(currentEvents.length) ?? []

            // Set meta timestamps when first chunk loads. The first time is a guesstimate that's later corrected by
            // the time the whole chunk loads.
            if (values.chunkIndex === 1) {
                const startOffset = eventsToAdd?.[0]?.timestamp ?? currentEvents?.[0]?.timestamp ?? 0
                const duration = sessionPlayerData?.duration ?? 0
                actions.setMeta({
                    startTime: startOffset,
                    endTime: startOffset + duration,
                    totalTime: duration,
                })
            }

            if (eventsToAdd.length < 1 || !values.replayer) {
                return
            }

            const lastEvent = eventsToAdd[eventsToAdd.length - 1]

            eventsToAdd.forEach((event: eventWithTime) => {
                values.replayer?.addEvent(event)
            })

            // Update last buffered point
            actions.setLastBufferedTime(lastEvent.timestamp)

            // If buffering has completed, resume last playing state
            if (
                values.currentPlayerState === SessionPlayerState.BUFFER &&
                values.time.current + BUFFER_TIME_BUFFER_MS < lastEvent.timestamp
            ) {
                actions.clearLoadingState()
                actions.setPlay()
            }

            // Set meta once whole session recording loads
            if (!values.sessionPlayerDataLoading) {
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
            actions.seek(values.time.current, true)
            values.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
        },
        setPause: () => {
            actions.stopAnimation()
            values.replayer?.pause()
            values.replayer?.setConfig({ speed: values.speed }) // hotfix: speed changes on player state change
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

            // Start playing by default to trigger a replayer tick
            actions.setCurrentTime(time ?? 0)
            values.replayer?.play(nextTime)
            actions.updateAnimation()

            // If next time is greater than last buffered time, set to buffering
            if (nextTime > values.zeroOffsetTime.lastBuffered) {
                values.replayer?.pause()
                actions.setBuffer()
            }
            // If not forced to play and if last playing state was pause, pause
            else if (!forcePlay && values.currentPlayerState === SessionPlayerState.PAUSE) {
                values.replayer?.pause()
                actions.clearLoadingState()
                actions.setPause()
            }
            // Otherwise keep playing and updating animation frame

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
            actions.setCurrentTime(nextTime)
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
})
