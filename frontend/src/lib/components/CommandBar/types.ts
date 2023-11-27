export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
    SHOW_SHORTCUTS = 'show_shortcuts',
}

export type ResultTypePostgres =
    | 'action'
    | 'cohort'
    | 'insight'
    | 'dashboard'
    | 'experiment'
    | 'feature_flag'
    | 'notebook'
export type ResultTypeClickhouse = 'person'
export type ResultType = ResultTypePostgres | ResultTypeClickhouse
export type ResultTypeWithAll = ResultType | 'all'

export type SearchResult = {
    result_id: string
    type: ResultType
    rank: number | null
    extra_fields: Record<string, unknown>
}

export type SearchResponse = {
    results: SearchResult[]
    counts: Record<ResultType, number | null>
}
