import { PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

/** An auto-discovered value uses the value itself as its option id, so the URL and widget configs can store it. */
export function autoDiscoveredOption(value: string): QuickFilterOption {
    return { id: value, value, label: value, operator: PropertyOperator.Exact }
}

export function resolveQuickFilterOption(
    filter: Pick<QuickFilter, 'type' | 'options'>,
    optionId: string
): QuickFilterOption | null {
    if (filter.type === 'auto-discovery') {
        return optionId ? autoDiscoveredOption(optionId) : null
    }
    return filter.options.find((option) => option.id === optionId) ?? null
}

/** Keeps a selected value visible when it is not among the discovered values, for example a value restored from the URL. */
export function withSelectedOption(options: QuickFilterOption[], selectedOptionId: string | null): QuickFilterOption[] {
    if (!selectedOptionId || options.some((option) => option.id === selectedOptionId)) {
        return options
    }
    return [autoDiscoveredOption(selectedOptionId), ...options]
}
