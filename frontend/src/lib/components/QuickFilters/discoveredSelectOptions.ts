import type { LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { QuickFilterOption } from '~/types'

import { withSelectedOption } from './quickFilterOptions'

export function anyOptionLabel(filterName: string): string {
    return `Any ${filterName.toLowerCase() || 'items'}`
}

/**
 * Keyboard navigation in the searchable select starts at the first visible option. While a search runs,
 * the "Any" option and a pinned selection that does not match stay hidden, so ArrowDown and Enter pick a
 * match instead of clearing the filter. A hidden option still lets the trigger show the selected value.
 */
export function discoveredSelectOptions(
    filterName: string,
    discoveredOptions: QuickFilterOption[],
    selectedOptionId: string | null,
    search: string
): LemonSelectOptionLeaf<string | null>[] {
    const matchingIds = new Set(discoveredOptions.map((option) => option.id))
    return [
        { value: null, label: anyOptionLabel(filterName), hidden: !!search },
        ...withSelectedOption(discoveredOptions, selectedOptionId).map((option) => ({
            value: option.id,
            label: option.label,
            hidden: !!search && !matchingIds.has(option.id),
            // Discovered values are raw event data, so keep them out of autocapture and replay
            className: 'ph-no-capture',
        })),
    ]
}
