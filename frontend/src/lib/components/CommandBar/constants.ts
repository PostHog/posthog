import { ResultTypeWithAll } from './types'

export const resultTypeToName: Record<ResultTypeWithAll, string> = {
    all: 'All',
    action: 'Action',
    cohort: 'Cohort',
    dashboard: 'Dashboard',
    experiment: 'Experiment',
    feature_flag: 'Feature Flag',
    insight: 'Insight',
}
