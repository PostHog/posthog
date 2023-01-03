import { ActionFilter, ActorType, FilterType, GraphDataset, TrendResult } from '~/types'

export interface TrendResponse {
    result: TrendResult[]
    filters: FilterType
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    id: number
    // if the sorting changes (e.g. for pie chart) we lose the original index
    // the series index is used for e.g. to get series color correctly
    seriesIndex: number
}

export interface TrendActors {
    seriesId?: number // The series identifier for this particular point (i.e. index of series)
    people: ActorType[]
    count: number
    missingPersons: number
    day: string | number
    label: string
    action?: ActionFilter
    breakdown_value?: string | number
    next?: string
    loadingMore?: boolean
    funnelStep?: number
    pathsDropoff?: boolean
    crossDataset?: GraphDataset[]
}
