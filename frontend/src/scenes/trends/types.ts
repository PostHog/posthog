import { ActionFilter, FilterType, GroupActorType, PersonType, TrendResult } from '~/types'

export interface TrendResponse {
    result: TrendResult[]
    filters: FilterType
    next?: string
}

export interface IndexedTrendResult extends TrendResult {
    id: number
}

export interface TrendActors {
    people: PersonType[] | GroupActorType[]
    count: number
    day: string | number
    label: string
    action: ActionFilter | 'session'
    breakdown_value?: string | number
    next?: string
    loadingMore?: boolean
    funnelStep?: number
    pathsDropoff?: boolean
}
