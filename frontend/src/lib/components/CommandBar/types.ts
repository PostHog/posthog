import { PersonType, SearchableEntity, SearchResultType } from '~/types'

export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
    SHOW_SHORTCUTS = 'show_shortcuts',
}

export type ResultType = SearchableEntity | 'person'

export type PersonResult = {
    type: 'person'
    result_id: string
    extra_fields: PersonType
    rank: number
}

export type SearchResult = SearchResultType | PersonResult
