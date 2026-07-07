import { SessionTurn } from './extractSessionTurns'

// Idle gaps between turns are compressed so playback stays watchable; the
// per-turn "think" windows are floored (always visible) and capped.
export const IDLE_CAP_MS = 3000
const MIN_THINK_MS = 600
const THINK_CAP_MS = 12000
const MIN_USER_THINK_MS = 600

export interface SessionTimelineData {
    turnRevealsMs: number[] // turn appears; the user starts composing
    turnStartsMs: number[] // the user's request lands
    turnResponsesMs: number[] // the assistant's response lands
    durationMs: number
}

export function buildSessionTimeline(turns: SessionTurn[]): SessionTimelineData {
    if (!turns.length) {
        return { turnRevealsMs: [], turnStartsMs: [], turnResponsesMs: [], durationMs: 0 }
    }

    const rawStarts = turns.map((t) => new Date(t.trace.createdAt).getTime())
    const latencies = turns.map((t) => Math.round((t.trace.totalLatency ?? 0) * 1000))

    const turnRevealsMs: number[] = []
    const turnStartsMs: number[] = []
    const turnResponsesMs: number[] = []
    let cursor = 0
    turns.forEach((_, i) => {
        const rawIdle = i > 0 ? Math.max(rawStarts[i] - (rawStarts[i - 1] + latencies[i - 1]), 0) : 0
        const userThinkMs = Math.min(Math.max(rawIdle, MIN_USER_THINK_MS), IDLE_CAP_MS)
        turnRevealsMs.push(cursor)
        cursor += userThinkMs
        turnStartsMs.push(cursor)
        const thinkMs = Math.min(Math.max(latencies[i], MIN_THINK_MS), THINK_CAP_MS)
        cursor += thinkMs
        turnResponsesMs.push(cursor)
    })

    return { turnRevealsMs, turnStartsMs, turnResponsesMs, durationMs: cursor }
}
