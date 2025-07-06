import emojiRegex from 'emoji-regex'
import {
    LegacyRecordingFilters,
    RecordingUniversalFilters,
    type SessionRecordingMaskingConfig,
    type SessionRecordingMaskingLevel,
    UniversalFiltersGroup,
    UniversalFilterValue,
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
