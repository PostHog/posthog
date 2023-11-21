export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
}

export type ResultType = 'action' | 'cohort' | 'insight' | 'dashboard' | 'experiment' | 'feature_flag' | 'notebook'

export type ResultTypeWithAll = ResultType | 'all'

export type SearchResult = {
    result_id: string
    type: ResultType
    name: string | null
    extra_fields: Record<string, unknown>
}

export type SearchResponse = {
    results: SearchResult[]
    counts: Record<ResultType, number | null>
}
