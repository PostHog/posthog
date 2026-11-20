import { ConversationTurn } from '../types'

export const SLOW_WAIT_MS = 10_000
export const SILENCE_MS = 60_000

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

export function isSlowWait(waitMs: number | null): boolean {
    return waitMs !== null && waitMs >= SLOW_WAIT_MS
}

export function silenceBefore(previous: ConversationTurn | null, turn: ConversationTurn): number | null {
    if (previous === null) {
        return null
    }
    const previousEnd = Date.parse(previous.timestamp) + (previous.waitMs ?? 0)
    const silenceMs = Date.parse(turn.timestamp) - previousEnd
    return silenceMs >= SILENCE_MS ? silenceMs : null
}

export function formatSilence(ms: number): string {
    if (ms >= DAY_MS) {
        return `${Math.round(ms / DAY_MS)} d later`
    }
    if (ms >= HOUR_MS) {
        return `${Math.round(ms / HOUR_MS)} h later`
    }
    return `${Math.round(ms / MINUTE_MS)} min later`
}
