import { Sorting } from '@posthog/lemon-ui'

import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { AccountPersonApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { getTileRecord, getTileString, type AccountViewTileConfig } from './accountViewTileConfig'

export const ACCOUNT_PERSONS_PAGE_SIZE = 20

/** Extra person-property columns a viewer can add. The email column is always present and does not count. */
export const MAX_PERSON_PROPERTY_COLUMNS = 5

export const EMAIL_PROPERTY_KEY = 'email'

export const ACCOUNT_FIRST_SEEN_KEY = 'account_first_seen'
export const ACCOUNT_LAST_SEEN_KEY = 'account_last_seen'

const PROPERTY_SORT_PREFIX = 'property:'

export const DEFAULT_PERSONS_SORTING: Sorting = { columnKey: ACCOUNT_LAST_SEEN_KEY, order: -1 }

/** Table column key for a person property. The prefix keeps a property from colliding with an activity column. */
export const propertyColumnKey = (propertyKey: string): string => `${PROPERTY_SORT_PREFIX}${propertyKey}`

/** Maps the table's sorting onto the API's `order_by`: activity keys pass through, property columns lose their prefix. */
export function sortingToOrderBy(sorting: Sorting): string {
    const key = sorting.columnKey.startsWith(PROPERTY_SORT_PREFIX)
        ? sorting.columnKey.slice(PROPERTY_SORT_PREFIX.length)
        : sorting.columnKey
    return sorting.order === -1 ? `-${key}` : key
}

export type AccountPersonsSortColumn = 'account_first_seen' | 'account_last_seen' | 'property'

/** Analytics-safe name for the sorted column. Property keys can name customers, so they are never sent. */
export function sortColumnForAnalytics(sorting: Sorting | null): AccountPersonsSortColumn | null {
    if (!sorting) {
        return null
    }
    if (sorting.columnKey === ACCOUNT_FIRST_SEEN_KEY || sorting.columnKey === ACCOUNT_LAST_SEEN_KEY) {
        return sorting.columnKey
    }
    return 'property'
}

/** The email person property, or null when the person has none. Only a non-empty string counts. */
export function personEmail(person: Pick<AccountPersonApi, 'properties'>): string | null {
    const email = person.properties[EMAIL_PROPERTY_KEY]
    return typeof email === 'string' && email.trim() ? email.trim() : null
}

/** A filter the API can evaluate. The filter UI also emits half-built rows, which must not trigger a request. */
export function isCompletePersonPropertyFilter(filter: PersonPropertyFilter): boolean {
    if (filter.type !== PropertyFilterType.Person || !filter.key || !filter.operator) {
        return false
    }
    if (filter.operator === PropertyOperator.IsSet || filter.operator === PropertyOperator.IsNotSet) {
        return true
    }
    return Array.isArray(filter.value)
        ? filter.value.length > 0
        : filter.value !== undefined && filter.value !== null && filter.value !== ''
}

export function completePersonPropertyFilters(filters: PersonPropertyFilter[]): PersonPropertyFilter[] {
    return filters.filter(isCompletePersonPropertyFilter)
}

export function normalizePropertyColumns(keys: readonly string[]): string[] {
    return Array.from(new Set(keys.filter((key) => !!key && key !== EMAIL_PROPERTY_KEY))).slice(
        0,
        MAX_PERSON_PROPERTY_COLUMNS
    )
}

export function personPropertyDisplayValue(value: unknown): string | null {
    if (value === null || value === undefined || value === '') {
        return null
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

export interface PersistedPersonsConfig {
    searchTerm: string
    sorting: Sorting
    propertyColumns: string[]
    propertyFilters: PersonPropertyFilter[]
}

/** Reads saved tile config defensively: it is user-editable JSON, and a bad sort would make every request fail. */
export function parsePersistedPersonsConfig(config: AccountViewTileConfig | undefined): PersistedPersonsConfig {
    const rawColumns = config?.propertyColumns
    const propertyColumns = normalizePropertyColumns(
        Array.isArray(rawColumns) ? rawColumns.filter((key): key is string => typeof key === 'string') : []
    )

    const rawFilters = config?.propertyFilters
    const propertyFilters = Array.isArray(rawFilters)
        ? rawFilters.filter(
              (filter): filter is PersonPropertyFilter =>
                  !!filter && typeof filter === 'object' && filter.type === PropertyFilterType.Person
          )
        : []

    const rawSorting = getTileRecord(config, 'sorting')
    const sortableKeys = new Set([
        ACCOUNT_FIRST_SEEN_KEY,
        ACCOUNT_LAST_SEEN_KEY,
        propertyColumnKey(EMAIL_PROPERTY_KEY),
        ...propertyColumns.map(propertyColumnKey),
    ])
    const sorting =
        rawSorting &&
        typeof rawSorting.columnKey === 'string' &&
        sortableKeys.has(rawSorting.columnKey) &&
        (rawSorting.order === 1 || rawSorting.order === -1)
            ? ({ columnKey: rawSorting.columnKey, order: rawSorting.order } as Sorting)
            : DEFAULT_PERSONS_SORTING

    return { searchTerm: getTileString(config, 'searchTerm'), sorting, propertyColumns, propertyFilters }
}
