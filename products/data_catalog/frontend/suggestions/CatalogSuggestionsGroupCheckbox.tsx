import { useActions, useValues } from 'kea'

import { SUGGESTED_MODEL_SECTIONS } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import type { SuggestionGroup } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'
import { warehouseSuggestionsSectionLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { PageSelectionCheckbox } from '../components/PageSelectionCheckbox'

export function CatalogSuggestionsGroupCheckbox({ group }: { group: SuggestionGroup }): JSX.Element {
    const { selectableIdsByKind, selectedIds } = useValues(warehouseSuggestionsSectionLogic)
    const { setSelected } = useActions(warehouseSuggestionsSectionLogic)

    return (
        <PageSelectionCheckbox
            label={`Select every ${SUGGESTED_MODEL_SECTIONS[group.kind]?.title ?? group.kind} suggestion`}
            pageIds={selectableIdsByKind[group.kind] ?? []}
            selectedIds={selectedIds}
            onChange={setSelected}
        />
    )
}
