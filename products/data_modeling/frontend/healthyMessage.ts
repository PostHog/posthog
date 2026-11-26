import { pluralize } from 'lib/utils/strings'

export type ChecksHealth = 'none' | 'all-passed' | 'some-not-passed' | 'failing'

const MODELS_CLAUSE = 'No models failed to refresh, are suspended, or are behind schedule.'
const CHECKS_CLAUSES: Record<ChecksHealth, string | null> = {
    'all-passed': 'All checks passed.',
    'some-not-passed': "No checks are failing. Some haven't passed yet.",
    none: null,
    failing: null,
}

export function healthyMessage(checksHealth: ChecksHealth): string {
    const checksClause = CHECKS_CLAUSES[checksHealth]
    return checksClause ? `${MODELS_CLAUSE} ${checksClause}` : MODELS_CLAUSE
}

export interface RefreshSummary {
    materializedCount: number
    lastRefreshAt: string | null
}

export function materializedModelsMessage(materializedCount: number): string | null {
    return materializedCount > 0 ? `${pluralize(materializedCount, 'materialized model')}.` : null
}
