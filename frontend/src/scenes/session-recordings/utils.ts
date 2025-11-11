import emojiRegex from 'emoji-regex'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    LegacyRecordingFilters,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    type SessionRecordingMaskingConfig,
    type SessionRecordingMaskingLevel,
    UniversalFilterValue,
    UniversalFiltersGroup,
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
    const group = filters.filter_group.values[0] as UniversalFiltersGroup
    return group.values as UniversalFilterValue[]
}

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

export function applyRecordingPropertyFilter(
    propertyKey: string,
    propertyValue: string | undefined,
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void,
    setIsFiltersExpanded: (expanded: boolean) => void
): void {
    // Validate property value
    if (propertyValue === undefined || propertyValue === null) {
        return
    }

    // Determine property filter type
    const isPersonProperty =
        propertyKey.startsWith('$geoip_') ||
        ['$browser', '$os', '$device_type', '$initial_device_type'].includes(propertyKey) ||
        !propertyKey.startsWith('$')

    const filterType = isPersonProperty ? PropertyFilterType.Person : PropertyFilterType.Session

    // Create property filter object
    const filter = {
        type: filterType,
        key: propertyKey,
        value: propertyValue,
        operator: PropertyOperator.Exact,
    }

    // Clone the current filter group structure and add to the first nested group
    const currentGroup = filters.filter_group
    const newGroup = {
        ...currentGroup,
        values: currentGroup.values.map((nestedGroup, index) => {
            // Add to the first nested group (index 0)
            if (index === 0 && 'values' in nestedGroup) {
                return {
                    ...nestedGroup,
                    values: [...nestedGroup.values, filter],
                }
            }
            return nestedGroup
        }),
    }

    setFilters({ filter_group: newGroup })

    // Show toast notification with human-readable label and view filters button
    const filterLabel = formatPropertyLabel(filter, {})
    lemonToast.success(`Filter applied: ${filterLabel}`, {
        toastId: `filter-applied-${propertyKey}`,
        button: {
            label: 'View filters',
            action: () => {
                setIsFiltersExpanded(true)
            },
        },
    })
}
