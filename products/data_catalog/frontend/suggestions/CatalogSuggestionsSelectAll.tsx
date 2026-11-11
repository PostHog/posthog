import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { warehouseSuggestionsSectionLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { PageSelectionCheckbox } from '../components/PageSelectionCheckbox'

export function CatalogSuggestionsSelectAll(): JSX.Element {
    const { selectableIds, selectedIds } = useValues(warehouseSuggestionsSectionLogic)
    const { setSelected } = useActions(warehouseSuggestionsSectionLogic)

    return (
        <label className="flex cursor-pointer items-center gap-2 px-3 py-2">
            <PageSelectionCheckbox
                label="Select all shown suggestions"
                pageIds={selectableIds}
                selectedIds={selectedIds}
                onChange={setSelected}
            />
            <Text size="xs" variant="muted" render={<span />}>
                Select all
            </Text>
        </label>
    )
}
