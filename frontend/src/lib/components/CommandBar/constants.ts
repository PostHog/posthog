import { ResultTypesWithAll } from './types'

export const resultTypeToName: Record<ResultTypesWithAll, string> = {
    all: 'All',
    action: 'Action',
    cohort: 'Cohort',
    dashboard: 'Dashboard',
    experiment: 'Experiment',
    feature_flag: 'Feature Flag',
    insight: 'Insight',
}
