import type { SessionListItemApi } from '../../generated/api.schemas'
import { formatCostUsd } from '../shared/formatCost'
import { formatLatencyMs } from '../trace/components/formatStats'

export function sessionFacts({ turnCount, durationMs, totals }: SessionListItemApi): string[] {
    return [
        turnCount === 1 ? '1 turn' : `${turnCount} turns`,
        durationMs !== null ? formatLatencyMs(durationMs) : null,
        totals.costUsd !== null ? formatCostUsd(totals.costUsd) : null,
    ].filter((fact): fact is string => fact !== null)
}
