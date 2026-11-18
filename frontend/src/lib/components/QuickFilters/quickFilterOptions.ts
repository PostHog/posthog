import { PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

// Auto-discovered option ids carry this prefix, so the URL and widget configs can store the value itself.
// Option ids from the manual form are UUIDs and never start with it. A stale manual id from an old link
// therefore does not resolve to a value after its filter switches to auto-discovery.
const DISCOVERED_OPTION_ID_PREFIX = '~'

export function autoDiscoveredOption(value: string): QuickFilterOption {
    return { id: `${DISCOVERED_OPTION_ID_PREFIX}${value}`, value, label: value, operator: PropertyOperator.Exact }
}

function discoveredValueFromOptionId(optionId: string): string | null {
    return optionId.startsWith(DISCOVERED_OPTION_ID_PREFIX) && optionId.length > DISCOVERED_OPTION_ID_PREFIX.length
        ? optionId.slice(DISCOVERED_OPTION_ID_PREFIX.length)
        : null
}

export function resolveQuickFilterOption(
    filter: Pick<QuickFilter, 'type' | 'options'>,
    optionId: string
): QuickFilterOption | null {
    if (filter.type === 'auto-discovery') {
        const value = discoveredValueFromOptionId(optionId)
        return value === null ? null : autoDiscoveredOption(value)
    }
    return filter.options.find((option) => option.id === optionId) ?? null
}

/** Keeps a selected value visible when it is not among the discovered values, for example a value restored from the URL. */
export function withSelectedOption(options: QuickFilterOption[], selectedOptionId: string | null): QuickFilterOption[] {
    if (!selectedOptionId || options.some((option) => option.id === selectedOptionId)) {
        return options
    }
    const value = discoveredValueFromOptionId(selectedOptionId)
    return value === null ? options : [autoDiscoveredOption(value), ...options]
}
