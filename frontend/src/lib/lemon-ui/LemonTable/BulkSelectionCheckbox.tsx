import { useContext } from 'react'

import { LemonCheckbox, LemonCheckboxProps } from '../LemonCheckbox'
import { bulkSelectionContext } from './bulkSelectionContext'
import { BulkSelectionKey } from './useBulkSelection'

export function BulkSelectionCheckbox({
    selectionKey,
    ...props
}: Omit<LemonCheckboxProps, 'checked'> & { selectionKey?: BulkSelectionKey }): JSX.Element {
    const { selectedKeysSet, isAllOnPageSelected, isSomeOnPageSelected } = useContext(bulkSelectionContext)
    const checked =
        selectionKey === undefined
            ? isSomeOnPageSelected
                ? 'indeterminate'
                : isAllOnPageSelected
            : selectedKeysSet.has(selectionKey)

    return <LemonCheckbox {...props} checked={checked} />
}
