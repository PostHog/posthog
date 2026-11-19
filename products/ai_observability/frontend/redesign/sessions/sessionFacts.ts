import type { SessionListItemApi } from '../../generated/api.schemas'
import { formatCostUsd, formatLatencyMs } from '../trace/components/formatStats'

/** The turn count, duration and cost a session shows wherever it is named, leaving out the ones it lacks. */
export function sessionFacts({ turnCount, durationMs, totals }: SessionListItemApi): string[] {
    return [
        turnCount === 1 ? '1 turn' : `${turnCount} turns`,
        durationMs !== null ? formatLatencyMs(durationMs) : null,
        totals.costUsd !== null ? formatCostUsd(totals.costUsd) : null,
    ].filter((fact): fact is string => fact !== null)
}
