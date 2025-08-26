import { Group, PersonType, SearchResultType, SearchableEntity } from '~/types'

export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
    SHOW_SHORTCUTS = 'show_shortcuts',
}

export type ResultType = SearchableEntity | 'person' | 'group' | 'tree_item'

export type PersonResult = {
    type: 'person'
    result_id: string
    extra_fields: PersonType
    rank: number
}

export type GroupResult = {
    type: 'group'
    result_id: string
    extra_fields: Group
    rank: number
}

export type TreeItemResult = {
    type: 'tree_item'
    result_id: string
    extra_fields: {
        path: string
        category?: string
        iconType?: string
        href?: string
        type?: string
        [key: string]: any
        icon?: JSX.Element
    }
    rank: number
}

export type SearchResult = SearchResultType | PersonResult | GroupResult | TreeItemResult
