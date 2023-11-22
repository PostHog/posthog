import { ResultTypeWithAll } from './types'

export const resultTypeToName: Record<ResultTypeWithAll, string> = {
    all: 'All',
    action: 'Actions',
    cohort: 'Cohorts',
    dashboard: 'Dashboards',
    experiment: 'Experiments',
    feature_flag: 'Feature flags',
    insight: 'Insights',
    notebook: 'Notebooks',
}

export const actionScopeToName: Record<string, string> = {
    global: 'Global',
    insights: 'Insights',
}
