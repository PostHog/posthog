export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
}

export type ResultType = 'action' | 'cohort' | 'insight' | 'dashboard' | 'experiment' | 'feature_flag'

export type ResultTypeWithAll = ResultType | 'all'

export type SearchResult = { result_id: string; type: ResultType; name: string | null }

export type SearchResponse = {
    results: SearchResult[]
    counts: Record<ResultType, number | null>
}
