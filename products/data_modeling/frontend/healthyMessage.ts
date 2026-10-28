import { CHECKS_LIMIT, OverviewChecksStatus } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

const MODELS_CLAUSE = 'No failed, suspended or late models.'
const TRUNCATED_CHECKS_CLAUSE = `No failing checks among the first ${CHECKS_LIMIT}.`
const CHECKS_CLAUSES: Record<OverviewChecksStatus, string | null> = {
    'all-passed': 'All checks passed.',
    'some-not-passed': "No checks are failing. Some haven't passed yet.",
    none: null,
    unknown: null,
}

export function healthyMessage(checksStatus: OverviewChecksStatus, checksTruncated: boolean): string {
    const checksClause = checksTruncated ? TRUNCATED_CHECKS_CLAUSE : CHECKS_CLAUSES[checksStatus]
    return checksClause ? `${MODELS_CLAUSE} ${checksClause}` : MODELS_CLAUSE
}
