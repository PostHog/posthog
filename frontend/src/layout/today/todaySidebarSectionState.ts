export type TodaySidebarSectionState = 'loading' | 'error' | 'empty' | 'no-matches' | 'ready'

export interface TodaySidebarSectionInput {
    loading: boolean
    failed: boolean
    total: number
    shown: number
}

export function todaySidebarSectionState({
    loading,
    failed,
    total,
    shown,
}: TodaySidebarSectionInput): TodaySidebarSectionState {
    if (total === 0) {
        return loading ? 'loading' : failed ? 'error' : 'empty'
    }
    return shown === 0 ? 'no-matches' : 'ready'
}

export function todayRecentClearLabel(searching: boolean, filtering: boolean): string {
    if (searching && filtering) {
        return 'Clear search and filters'
    }
    return searching ? 'Clear search' : 'Clear filters'
}
