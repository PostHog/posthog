/**
 * New evaluations whose creator asked to also evaluate past traffic. It lives in memory, not in the URL,
 * so a link cannot start a backfill, and a request survives leaving the Backfills tab before its count lands.
 */
const requested = new Set<string>()

export function requestBackfillStart(evaluationId: string): void {
    requested.add(evaluationId)
}

/** Returns whether a start was requested, and forgets it, so each request starts at most one backfill. */
export function takeBackfillStart(evaluationId: string): boolean {
    return requested.delete(evaluationId)
}
