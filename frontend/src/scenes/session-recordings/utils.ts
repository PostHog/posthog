import emojiRegex from 'emoji-regex'

import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'

import {
    type ActionFilter,
    type EventPropertyFilter,
    FilterLogicalOperator,
    LegacyRecordingFilters,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    type SessionRecordingMaskingConfig,
    type SessionRecordingMaskingLevel,
    UniversalFilterValue,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

export const TimestampFormatToLabel = {
    relative: 'Relative',
    utc: 'UTC',
    device: 'Device',
}

export const isUniversalFilters = (
    filters: RecordingUniversalFilters | LegacyRecordingFilters
): filters is RecordingUniversalFilters => {
    return 'filter_group' in filters
}

// TODO we shouldn't be ever converting to filters any more, but I won't unpick this in this PR
export const filtersFromUniversalFilterGroups = (filters: RecordingUniversalFilters): UniversalFilterValue[] => {
    // Some saved filters store values at the top level rather than nested in values[0], so recurse.
    const flatten = (items: UniversalFiltersGroupValue[] | undefined): UniversalFilterValue[] => {
        if (!Array.isArray(items)) {
            return []
        }
        return items.flatMap((item) =>
            item &&
            typeof item === 'object' &&
            'values' in item &&
            Array.isArray((item as UniversalFiltersGroup).values)
                ? flatten((item as UniversalFiltersGroup).values)
                : [item as UniversalFilterValue]
        )
    }
    return flatten(filters.filter_group.values)
}

// The properties people reach for when they mean "show me sessions that visited this page".
const PAGE_PROPERTY_KEYS = ['$current_url', '$pathname']

type PageProperty = { key?: unknown; operator?: PropertyOperator; value?: any }

const isPagePropertyFilter = (filter: PageProperty): boolean =>
    PAGE_PROPERTY_KEYS.includes(filter.key as string) &&
    !!filter.operator &&
    filter.value != null &&
    filter.value !== '' &&
    !(Array.isArray(filter.value) && filter.value.length === 0)

// Operators `visited_page` answers the same way a pageview filter does. Negated forms are included,
// but only swap inside "match all" groups (see NEGATED_PAGE_OPERATORS below).
// Ordering and is_set/is_not_set are left out: they compare a recording's URL list, not a page.
const VISITED_PAGE_SAFE_OPERATORS: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
]

// Under "match all" (AND) the backend turns a negated event property into a session-level exclusion
// (the negative blocklist in ReplayFiltersEventsSubQuery), which is what a negated `visited_page`
// means: "no URL matches". Under "match any" (OR) the same filter is existential, "some pageview
// doesn't match", which a negated `visited_page` inverts. So these only swap inside AND-only groups.
const NEGATED_PAGE_OPERATORS: PropertyOperator[] = [
    PropertyOperator.IsNot,
    PropertyOperator.NotIContains,
    PropertyOperator.NotRegex,
]

// Recorded URLs are absolute, so an exact `$pathname` value or an anchored `$pathname` pattern
// (e.g. `^/docs`) would stop matching once rewritten. Only substring matches still line up.
const PATHNAME_SAFE_OPERATORS: PropertyOperator[] = [PropertyOperator.IContains, PropertyOperator.NotIContains]

const isSwappablePageProperty = (filter: PageProperty): boolean =>
    isPagePropertyFilter(filter) &&
    VISITED_PAGE_SAFE_OPERATORS.includes(filter.operator!) &&
    (filter.key !== '$pathname' || PATHNAME_SAFE_OPERATORS.includes(filter.operator!))

const isSwappablePageFilter = (filter: UniversalFilterValue): boolean =>
    filter.type === PropertyFilterType.Event && isSwappablePageProperty(filter)

/**
 * A pageview event filter is the other way people express "visited this page". It only maps cleanly onto
 * `visited_page` when the URL property is the only thing scoping the event, and nothing is negated:
 * a negated entity means "sessions without any matching pageview", and a negated URL property compiles
 * to an existential predicate ("session has a pageview whose URL doesn't match", still requiring a
 * pageview to exist), while a negated `visited_page` means "no recorded URL matches" with no such
 * requirement.
 */
const isSwappablePageviewFilter = (filter: UniversalFilterValue): boolean => {
    if (!isEventFilter(filter) || filter.id !== '$pageview' || filter.negation) {
        return false
    }
    const properties = filter.properties ?? []
    return (
        properties.length === 1 &&
        properties[0].type === PropertyFilterType.Event &&
        isSwappablePageProperty(properties[0]) &&
        !NEGATED_PAGE_OPERATORS.includes(properties[0].operator!)
    )
}

const pagePropertiesOf = (filter: UniversalFilterValue): PageProperty[] =>
    isEventFilter(filter) || isActionFilter(filter) ? (filter.properties ?? []) : [filter]

const usesNegatedPageOperator = (filter: UniversalFilterValue): boolean =>
    pagePropertiesOf(filter).some(
        (property) => isPagePropertyFilter(property) && NEGATED_PAGE_OPERATORS.includes(property.operator!)
    )

const isAndOnlyGroup = (group: UniversalFiltersGroup): boolean =>
    group.type === FilterLogicalOperator.And &&
    group.values.every(
        (value) =>
            !(value && typeof value === 'object' && 'values' in value && Array.isArray(value.values)) ||
            isAndOnlyGroup(value)
    )

/**
 * True when the filters express "sessions that visited page X". Those match pageview events from anywhere
 * in the session, so they can match a moment the video never covers, unlike `visited_page`.
 */
export const hasPageFilter = (filters: RecordingUniversalFilters): boolean =>
    filtersFromUniversalFilterGroups(filters).some((filter) => pagePropertiesOf(filter).some(isPagePropertyFilter))

// The backend routes `visited_page` into HAVING, where it is AND'd against the event filters it
// used to share a group with, so swapping one member of a match-any group turns the union into an
// intersection. A match-any group is only safe when every member is a page filter being swapped:
// then the whole group survives as one OR of `visited_page` predicates.
const orGroupsContainOnlySwappablePageFilters = (group: UniversalFiltersGroup): boolean =>
    group.values.every((value) => {
        if (value && typeof value === 'object' && 'values' in value && Array.isArray(value.values)) {
            return orGroupsContainOnlySwappablePageFilters(value)
        }
        if (group.type !== FilterLogicalOperator.Or) {
            return true
        }
        const filter = value as UniversalFilterValue
        return isSwappablePageFilter(filter) || isSwappablePageviewFilter(filter)
    })

/** Whether every page filter can be rewritten to `visited_page` without changing which recordings match. */
export const canSwapPageFiltersForVisitedPage = (filters: RecordingUniversalFilters): boolean => {
    const filterList = filtersFromUniversalFilterGroups(filters)
    const pageFilters = filterList.filter((filter) => pagePropertiesOf(filter).some(isPagePropertyFilter))
    const negatedSwapIsSafe = isAndOnlyGroup(filters.filter_group)
    return (
        pageFilters.length > 0 &&
        orGroupsContainOnlySwappablePageFilters(filters.filter_group) &&
        pageFilters.every(
            (filter) =>
                (isSwappablePageFilter(filter) || isSwappablePageviewFilter(filter)) &&
                (negatedSwapIsSafe || !usesNegatedPageOperator(filter))
        )
    )
}

const toVisitedPageFilter = (property: { operator?: PropertyOperator; value?: any }): UniversalFilterValue =>
    ({
        type: PropertyFilterType.Recording,
        key: 'visited_page',
        operator: property.operator,
        value: property.value,
    }) as UniversalFilterValue

/** Rewrites every swappable page filter to the equivalent `visited_page` one, at any nesting depth. */
export const swapPageFiltersForVisitedPage = (group: UniversalFiltersGroup): UniversalFiltersGroup => ({
    ...group,
    values: group.values.map((value) => {
        if (value && typeof value === 'object' && 'values' in value && Array.isArray(value.values)) {
            return swapPageFiltersForVisitedPage(value)
        }
        const filter = value as UniversalFilterValue
        if (isSwappablePageFilter(filter)) {
            return toVisitedPageFilter(filter as EventPropertyFilter)
        }
        if (isSwappablePageviewFilter(filter)) {
            return toVisitedPageFilter((filter as ActionFilter).properties![0])
        }
        return value
    }),
})

export const getMaskingLevelFromConfig = (config: SessionRecordingMaskingConfig): SessionRecordingMaskingLevel => {
    if (config.maskTextSelector === '*' && config.maskAllInputs && config.blockSelector === 'img') {
        return 'total-privacy'
    }

    if (config.maskTextSelector === undefined && config.maskAllInputs === false) {
        return 'free-love'
    }

    return 'normal'
}

export const getMaskingConfigFromLevel = (level: SessionRecordingMaskingLevel): SessionRecordingMaskingConfig => {
    if (level === 'total-privacy') {
        return { maskTextSelector: '*', maskAllInputs: true, blockSelector: 'img' }
    }

    if (level === 'free-love') {
        return { maskTextSelector: undefined, maskAllInputs: false, blockSelector: undefined }
    }

    return { maskTextSelector: undefined, maskAllInputs: true, blockSelector: undefined }
}

export function isSingleEmoji(s: string): boolean {
    const graphemes = Array.from(new Intl.Segmenter('und', { granularity: 'grapheme' }).segment(s))
    if (graphemes.length !== 1) {
        return false
    }

    // NB: this regex must be created inside the function
    // or the second emoji it checks always results in false 🤷
    const regex = emojiRegex()
    return regex.test(graphemes[0].segment)
}
