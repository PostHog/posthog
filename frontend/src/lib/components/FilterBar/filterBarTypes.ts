import type { ComponentType } from 'react'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

/** Where a field comes from. Group properties get one category per group type, keyed by its index. */
export type FilterBarCategoryId =
    | 'event_properties'
    | 'person_properties'
    | 'session_properties'
    | 'feature_flags'
    | 'cohorts'
    | 'elements'
    | 'sql'
    | `group_properties_${number}`

export interface FilterBarCategory {
    id: FilterBarCategoryId
    label: string
    /** Used in the search placeholder of the category's own list, for example "event properties". */
    plural: string
    propertyFilterType: PropertyFilterType
    groupTypeIndex?: number
    /** `primary` categories show on the first screen of the picker, `more` ones sit behind "More". */
    tier: 'primary' | 'more'
}

/** One thing a person can filter on: a property, a cohort, an element attribute or a SQL expression. */
export interface FilterBarField {
    categoryId: FilterBarCategoryId
    /** The property name, the cohort id as a string, the element attribute, or the SQL expression. */
    key: string
    label: string
    propertyType?: PropertyType | null
    description?: string | null
    /**
     * Where a category's browse list puts the field: the project's own properties, or the PostHog ones with a known
     * label. Fields without a group show in one flat list.
     */
    group?: 'project' | 'posthog'
}

export type FilterBarValueKind = 'list' | 'number' | 'date' | 'boolean' | 'cohort' | 'sql' | 'none'

export interface FilterBarOperatorOption {
    value: PropertyOperator
    label: string
}

/** Where a filter was picked from in the add menu. Recorded in analytics to learn which entry points earn their place. */
export type FilterBarAddSource = 'recent' | 'popular' | 'search' | 'category' | 'saved' | 'sql'

export interface FilterBarItem {
    /** Stable across edits, so React keys and the open menu survive a value change. */
    id: number
    filter: AnyPropertyFilter
}

export interface FilterBarSavedSet {
    id: string
    name: string
    filters: AnyPropertyFilter[]
    createdAt: number
}

export interface FilterBarControl {
    id: string
    label: string
    icon: ComponentType
    hasValue: boolean
    /** The chip always shows, with a default value when `hasValue` is false, so the add menu leaves the control out. */
    persistent?: boolean
    open: () => void
    clear: () => void
}
