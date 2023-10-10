export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
}

export type SearchResults = {
    results: { pk: number; type: string; name: string | null }[]
    counts: {
        dashboards: number
        experiments: number
        feature_flags: number
    }
}
