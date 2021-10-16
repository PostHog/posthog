import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SessionPlayerState, SessionPlayerTime } from '~/types'
import { eventWithTime, playerMetaData } from 'rrweb/typings/types'
import { sessionsPlayLogic } from 'scenes/sessions/sessionsPlayLogic'

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4, 8, 16]

function getTime(time: number, meta: playerMetaData): number {
    return Math.max(Math.min(time, meta.endTime), 0)
}

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [
            sessionsPlayLogic,
            ['sessionRecordingId', 'sessionPlayerData', 'sessionPlayerDataLoading', 'isPlayable'],
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
        setMeta: (meta: playerMetaData) => ({ meta }),
        setCurrentTime: (time: number) => ({ time }),
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
            },
        ],
        playingState: [
            SessionPlayerState.PLAY as SessionPlayerState,
            {
                setPlay: () => SessionPlayerState.PLAY,
                setPause: () => SessionPlayerState.PAUSE,
            },
        ],
        loadingState: [
            SessionPlayerState.BUFFER as SessionPlayerState.BUFFER | SessionPlayerState.SKIP | null,
            {
                setBuffer: () => SessionPlayerState.BUFFER,
                setSkip: () => SessionPlayerState.SKIP,
                clearLoadingState: () => null,
            },
        ],
    }),
    selectors: {
        currentPlayerState: [
            (selectors) => [selectors.playingState, selectors.loadingState],
            (playingState, loadingState) => loadingState ?? playingState,
        ],
        duration: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => sessionPlayerData?.duration ?? 0,
        ],
        jumpTimeMs: [(selectors) => [selectors.speed], (speed) => 10 * 1000 * speed],
        snapshots: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => sessionPlayerData?.snapshots ?? [],
        ],
    },
    listeners: ({ values, actions, cache }) => ({
        initReplayer: ({ frame }) => {
            console.log('INIT REPLAYER', frame, values.snapshots)

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
                if (values.loadingState !== SessionPlayerState.BUFFER) {
                    actions.clearLoadingState()
                }
            })

            actions.setReplayer(replayer)
        },
        setReplayer: () => {
            actions.setPlay()
        },
        loadRecordingSuccess: () => {
            // On loading more of the recording, trigger some state changes
            const currentEvents = values.replayer?.service.state.context.events ?? []
            const eventsToAdd = values.snapshots.slice(currentEvents.length) ?? []

            if (eventsToAdd.length < 1) {
                return
            }

            const lastEvent = eventsToAdd[eventsToAdd.length - 1]
            eventsToAdd.forEach((event: eventWithTime) => values.replayer?.addEvent(event))

            // Update last buffered point
            actions.setLastBufferedTime(lastEvent.timestamp)

            // If buffering has completed, resume last playing state
            if (values.currentPlayerState === SessionPlayerState.BUFFER) {
                actions.clearLoadingState()
            }

            // If entire recording isn't finished loading, set meta timestamps
            if (values.sessionPlayerDataLoading && values.replayer) {
                const meta = values.replayer?.getMetaData()
                actions.setMeta(meta)
            }
        },
        setPlay: () => {
            actions.stopAnimation()
            values.replayer?.play(values.time.current)
            console.log('ANIMATION META', values.meta)
            actions.updateAnimation()
        },
        setPause: () => {
            actions.stopAnimation()
            values.replayer?.pause()
        },
        setBuffer: () => {
            actions.stopAnimation()
        },
        setSpeed: ({ speed }) => {
            values.replayer?.setConfig({ speed })
        },
        seek: async ({ time, forcePlay }, breakpoint) => {
            breakpoint()

            const nextTime = getTime(time, values.meta)
            if (forcePlay) {
                values.replayer?.play(nextTime)
            }
            // If next time is greater than last buffered time, set to buffering
            if (nextTime >= values.time.lastBuffered) {
                actions.setBuffer()
            }
            // If seek position has already been loaded, resume last playing state
            else {
                actions.clearLoadingState()
            }

            await breakpoint(10)
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
            console.log('UPDATE ANIMATION', values.replayer?.getCurrentTime())
            const nextTime = getTime(values.replayer?.getCurrentTime() ?? 0, values.meta)
            actions.setCurrentTime(nextTime)
            cache.timer = requestAnimationFrame(actions.updateAnimation)
        },
        stopAnimation: () => {
            if (cache.timer) {
                cancelAnimationFrame(cache.timer)
            }
        },
    }),
})
