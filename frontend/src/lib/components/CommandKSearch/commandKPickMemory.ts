export interface PickInput {
    input: string
    picks: Record<string, number>
    updatedAt: number
}

export const PICK_MEMORY_LIMIT = 200
export const PICKED_THRESHOLD = 0.5

const PICK_RETENTION = 0.9
const DAILY_DECAY = 0.975
const DAY_MS = 24 * 60 * 60 * 1000

const decayed = (score: number, from: number, to: number): number =>
    score * Math.pow(DAILY_DECAY, Math.max(to - from, 0) / DAY_MS)

export function recordPick(memory: PickInput[], input: string, itemId: string, now: number): PickInput[] {
    if (!input) {
        return memory
    }
    const existing = memory.find((entry) => entry.input === input)
    const picks = Object.fromEntries(
        Object.entries(existing?.picks ?? {}).map(([id, score]) => [id, decayed(score, existing!.updatedAt, now)])
    )
    picks[itemId] = (picks[itemId] ?? 0) * PICK_RETENTION + 1
    const others = memory.filter((entry) => entry.input !== input)
    return [{ input, picks, updatedAt: now }, ...others].slice(0, PICK_MEMORY_LIMIT)
}

export function pickScores(memory: PickInput[], typed: string, now: number): Map<string, number> {
    const scores = new Map<string, number>()
    if (!typed) {
        return scores
    }
    for (const entry of memory) {
        if (!entry.input.startsWith(typed)) {
            continue
        }
        for (const [id, score] of Object.entries(entry.picks)) {
            const current = decayed(score, entry.updatedAt, now)
            if (current > (scores.get(id) ?? 0)) {
                scores.set(id, current)
            }
        }
    }
    return scores
}
