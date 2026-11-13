import { useActions, useValues } from 'kea'

import { Checkbox, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { WarehouseSuggestionApi } from 'products/warehouse_suggestions/frontend/generated/api.schemas'
import { suggestionBlockedReason } from 'products/warehouse_suggestions/frontend/suggestionBlockedReason'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'
import { warehouseSuggestionsSectionLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

export function CatalogSuggestionCheckbox({ suggestion }: { suggestion: WarehouseSuggestionApi }): JSX.Element {
    const { selectedIds } = useValues(warehouseSuggestionsSectionLogic)
    const { toggleSelected } = useActions(warehouseSuggestionsSectionLogic)
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const blockedReason = suggestionBlockedReason(
        suggestion,
        actionsInFlight,
        leavingSuggestionIds.includes(suggestion.id)
    )
    const checkbox = (
        <Checkbox
            aria-label={`Select ${suggestion.payload.subject_name}`}
            checked={selectedIds.includes(suggestion.id)}
            disabled={!!blockedReason}
            onCheckedChange={() => toggleSelected(suggestion.id)}
            data-attr="data-catalog-suggestions-select"
        />
    )
    if (!blockedReason) {
        return checkbox
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="flex" />}>{checkbox}</TooltipTrigger>
            <TooltipContent>{blockedReason}</TooltipContent>
        </Tooltip>
    )
}
