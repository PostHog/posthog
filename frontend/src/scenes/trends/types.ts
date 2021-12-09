import { ActionFilter, ActorType, FilterType, TrendResult } from '~/types'

export interface TrendResponse {
    result: TrendResult[]
    filters: FilterType
    next?: string
}
export interface DatasetType {
    seriesId: number
    action: ActionFilter
    personUrl?: string
    breakdown_value?: string
    pointValue?: number // The y-axis value of the data point (i.e. count, unique persons, ...)
}

export interface IndexedTrendResult extends TrendResult {
    id: number
}

export interface TrendActors {
    seriesId?: number // The series identifier for this particular point (i.e. index of series)
    people: ActorType[]
    count: number
    day: string | number
    label: string
    action: ActionFilter | 'session'
    breakdown_value?: string | number
    next?: string
    loadingMore?: boolean
    funnelStep?: number
    pathsDropoff?: boolean
    crossDataset?: DatasetType[]
}
