import emojiRegex from 'emoji-regex'

import { isActionFilter, isEventFilter } from 'lib/components/UniversalFilters/utils'

import {
    LegacyRecordingFilters,
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

const pagePropertiesOf = (filter: UniversalFilterValue): PageProperty[] =>
    isEventFilter(filter) || isActionFilter(filter) ? (filter.properties ?? []) : [filter]

/**
 * True when the filters express "sessions that visited page X". Those match pageview events from anywhere
 * in the session, so they can match a moment the video never covers, unlike `visited_page`.
 */
export const hasPageFilter = (filters: RecordingUniversalFilters): boolean =>
    filtersFromUniversalFilterGroups(filters).some((filter) => pagePropertiesOf(filter).some(isPagePropertyFilter))

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
