import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import type { sessionPlaybackLogicType } from './sessionPlaybackLogicType'

export const PLAYBACK_SPEEDS = [0.5, 1, 1.5, 2, 3, 4, 8, 16]
const TICK_MS = 50

export interface SessionPlaybackLogicProps {
    sessionId: string
}

export const sessionPlaybackLogic = kea<sessionPlaybackLogicType>([
    path(['products', 'ai_observability', 'frontend', 'sessionPlaybackLogic']),
    props({} as SessionPlaybackLogicProps),
    key((props) => props.sessionId),

    actions({
        play: true,
        pause: true,
        togglePlay: true,
        seek: (ms: number) => ({ ms }),
        setSpeed: (speed: number) => ({ speed }),
        setTimeline: (durationMs: number) => ({ durationMs }),
        tick: (deltaMs: number) => ({ deltaMs }),
        setCurrentMs: (ms: number) => ({ ms }),
    }),

    reducers({
        playing: [false, { play: () => true, pause: () => false, seek: () => false }],
        speed: [1, { setSpeed: (_, { speed }) => speed }],
        durationMs: [0, { setTimeline: (_, { durationMs }) => durationMs }],
        currentMs: [
            0,
            {
                seek: (_, { ms }) => Math.max(ms, 0),
                setCurrentMs: (_, { ms }) => Math.max(ms, 0),
                // A late trace load can change total duration without changing the turn
                // count; keep the current position (clamped) instead of rewinding to 0.
                setTimeline: (state, { durationMs }) => Math.min(state, durationMs),
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        togglePlay: () => (values.playing ? actions.pause() : actions.play()),
        seek: () => cache.disposables.dispose('playback-tick'),
        tick: ({ deltaMs }) => {
            const next = Math.min(values.currentMs + deltaMs * values.speed, values.durationMs)
            actions.setCurrentMs(next)
            if (next >= values.durationMs) {
                actions.pause()
            }
        },
        play: () => {
            if (values.currentMs >= values.durationMs) {
                actions.setCurrentMs(0)
            }
            cache.disposables.add(() => {
                const id = setInterval(() => actions.tick(TICK_MS), TICK_MS)
                return () => clearInterval(id)
            }, 'playback-tick')
        },
        pause: () => cache.disposables.dispose('playback-tick'),
    })),
])
