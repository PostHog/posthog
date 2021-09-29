import { ActionFilter, FilterType, PersonType, TrendResult } from '~/types'

export interface TrendResponse {
    result: TrendResult[]
    filters: FilterType
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    id: number
}

export interface TrendPeople {
    people: PersonType[]
    count: number
    day: string | number
    label: string
    action: ActionFilter | 'session'
    breakdown_value?: string | number
    next?: string
    loadingMore?: boolean
    funnelStep?: number
}
