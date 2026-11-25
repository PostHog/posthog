import type { SessionTurnApi, TraceTurnApi } from '../../generated/api.schemas'
import { aiObservabilityTracesTurnsCreateBodyTraceIdsMax } from '../../generated/api.zod'
import type { CellLoads } from '../shared/cellLoads'
import type { ConversationTurn, NodeSideContent } from '../trace/types'

// The longest span `traces/turns/` reads in one request. Its schema carries no constant for it.
export const TURNS_REQUEST_MAX_SPAN_MS = 30 * 24 * 60 * 60 * 1000

const EMPTY_SIDE: NodeSideContent = { kind: 'messages', messages: [] }

/** The input and output of one turn, or null when the trace has nothing to show. */
export interface TurnSides {
    traceId: string
    turn: TraceTurnApi | null
}

/** Splits rows into the requests `traces/turns/` accepts, in the order the rows started. */
export function turnSidesBatches(rows: SessionTurnApi[]): SessionTurnApi[][] {
    const batches: SessionTurnApi[][] = []
    for (const row of [...rows].sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))) {
        const batch = batches[batches.length - 1]
        const fits =
            batch &&
            batch.length < aiObservabilityTracesTurnsCreateBodyTraceIdsMax &&
            Date.parse(row.createdAt) - Date.parse(batch[0].createdAt) <= TURNS_REQUEST_MAX_SPAN_MS
        if (fits) {
            batch.push(row)
        } else {
            batches.push([row])
        }
    }
    return batches
}

/** One answer per requested row. The read leaves out a trace with nothing to show, so that trace answers null. */
export function turnSidesOfRows(rows: SessionTurnApi[], items: TraceTurnApi[]): TurnSides[] {
    const turns = new Map(items.map((item) => [item.traceId, item]))
    return rows.map((row) => ({ traceId: row.id, turn: turns.get(row.id) ?? null }))
}

function conversationTurn(row: SessionTurnApi, sides: CellLoads<TraceTurnApi | null>): ConversationTurn {
    const turn = {
        id: row.id,
        timestamp: row.createdAt,
        waitMs: row.totals.latencyMs,
        waitSlow: row.waitSlow,
        silenceBeforeMs: row.silenceBeforeMs,
        error: row.firstError,
        trace: { name: row.name, totals: row.totals },
        input: EMPTY_SIDE,
        output: EMPTY_SIDE,
    }
    // A row whose read is not asked for yet is about to be, so it shows as loading.
    const load = sides.get(row.id) ?? { status: 'loading' }
    if (load.status !== 'ready') {
        return { ...turn, sidesStatus: load.status }
    }
    if (load.value === null) {
        return { ...turn, sidesStatus: 'ready' }
    }
    const { input, output, inputMissingReason, outputMissingReason } = load.value
    return {
        ...turn,
        input: input ?? EMPTY_SIDE,
        output: output ?? EMPTY_SIDE,
        sidesStatus: 'ready',
        ...((inputMissingReason || outputMissingReason) && {
            missingReasons: { input: inputMissingReason, output: outputMissingReason },
        }),
    }
}

/** The session's turns as the thread shows them: each row shows as soon as it loads, and its messages once they do. */
export function conversationTurns(rows: SessionTurnApi[], sides: CellLoads<TraceTurnApi | null>): ConversationTurn[] {
    return rows.map((row) => conversationTurn(row, sides))
}
