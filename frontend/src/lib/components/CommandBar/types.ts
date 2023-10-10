export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
}

export type ResultTypes = 'dashboard' | 'experiment' | 'feature_flag'

export type ResultTypesWithAll = ResultTypes | 'all'

export type SearchResult = { pk: number; type: ResultTypes; name: string | null }

export type SearchResponse = {
    results: SearchResult[]
    counts: Record<ResultTypes, number | null>
}
