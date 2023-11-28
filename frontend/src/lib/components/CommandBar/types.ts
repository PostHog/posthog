import { SearchableEntity } from '~/types'

export enum BarStatus {
    HIDDEN = 'hidden',
    SHOW_SEARCH = 'show_search',
    SHOW_ACTIONS = 'show_actions',
    SHOW_SHORTCUTS = 'show_shortcuts',
}

export type ResultType = SearchableEntity | 'person'
