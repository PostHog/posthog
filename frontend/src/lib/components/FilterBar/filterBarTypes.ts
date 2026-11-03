import type { ComponentType } from 'react'

import {
    ActionFilter,
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
    UniversalFiltersGroup,
} from '~/types'

/** Where a field comes from. Group properties get one category per group type, keyed by its index. */
export type FilterBarCategoryId =
    | 'event_properties'
    | 'person_properties'
    | 'session_properties'
    | 'feature_flags'
    | 'cohorts'
    | 'elements'
    | 'sql'
    | 'events'
    | `group_properties_${number}`
    | `custom_${string}`

export interface FilterBarCategory {
    id: FilterBarCategoryId
    label: string
    /** Used in the search placeholder of the category's own list, for example "event properties". */
    plural: string
    propertyFilterType: PropertyFilterType
    groupTypeIndex?: number
    /** `primary` categories show on the first screen of the picker, `more` ones sit behind "More". */
    tier: 'primary' | 'more'
    /** The bar offers the category only when `categoryIds` names it, because not every surface can store its filters. */
    optIn?: boolean
}

/**
 * A filter type one surface owns, such as recording or log attributes. A surface registers it once with
 * `registerFilterBarCategory` and lists its id in `categoryIds`. Other bars still edit a stored filter of this type.
 */
export interface FilterBarCategoryDefinition extends Omit<FilterBarCategory, 'id' | 'optIn'> {
    id: `custom_${string}`
    icon: ComponentType<{ className?: string }>
    fetchFields: (query: string) => FilterBarField[] | Promise<FilterBarField[]>
    /** The values the picker offers for a field. Without it, a person types the value. */
    fetchValues?: (key: string, query: string) => string[] | Promise<string[]>
    /** Limits the operators the chip offers. Without it, the chip offers the ones for the field's property type. */
    operators?: PropertyOperator[]
    propertyType?: (key: string) => PropertyType | null
    fieldLabel?: (key: string) => string
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

/** An event or action, with the property filters that narrow it. */
export interface FilterBarEventNode {
    id: number
    event: Omit<ActionFilter, 'properties'>
    items: FilterBarItem[]
}

/** Rows joined by one operator. A row can be a group, so a tree of any depth round-trips. */
export interface FilterBarGroupNode {
    id: number
    type: FilterLogicalOperator
    children: FilterBarNode[]
}

export type FilterBarNode = FilterBarItem | FilterBarEventNode | FilterBarGroupNode

/** What a surface stores: a flat AND list, or a group that can hold OR branches and events. */
export type FilterBarValue = AnyPropertyFilter[] | UniversalFiltersGroup

export interface FilterBarSavedSet {
    id: string
    name: string
    filters: AnyPropertyFilter[]
    /** Set when the filters use groups or events. Only a bar that stores groups offers such a set. */
    group?: UniversalFiltersGroup
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
