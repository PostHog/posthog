import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { BulkTaggableResource, listSelectionLogic, PageItem } from 'lib/logic/listSelectionLogic'

export function SelectionCheckbox({
    resource,
    id,
    index,
    allPageItems,
    disabledReason,
    ariaLabel,
}: {
    resource: BulkTaggableResource
    id: number
    index: number
    allPageItems: PageItem[]
    disabledReason?: string
    ariaLabel?: string
}): JSX.Element {
    const logic = listSelectionLogic({ resource })
    const { selectedIdsSet } = useValues(logic)
    const { toggleSelection } = useActions(logic)

    return (
        <LemonCheckbox
            checked={selectedIdsSet.has(id)}
            onChange={() => toggleSelection(id, index, allPageItems)}
            disabledReason={disabledReason}
            aria-label={ariaLabel}
        />
    )
}
