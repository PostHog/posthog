import { useActions, useValues } from 'kea'

import { IconLock, IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { FilterLogicalOperator } from '~/types'

import { FilterBarChipMenu } from './FilterBarChipMenu'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarItem } from './filterBarTypes'

/**
 * A stored filter of a type the bar has no editor for. The filter still applies, so the chip shows it and a person can
 * remove it, and the bar hands it back to the surface unchanged.
 */
export function FilterBarUnsupportedChip({
    item,
    wrapType,
}: {
    item: FilterBarItem
    wrapType?: FilterLogicalOperator | null
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { removeItem } = useActions(filterBarLogic)
    const label = formatPropertyLabel(item.filter, cohortsById).trim() || String(item.filter.key)

    return (
        <ButtonGroup className="max-w-full" data-attr="filter-bar-chip-unsupported">
            <Button
                variant="outline"
                className="min-w-0 max-w-96"
                disabledReason="This filter applies, but you can't edit it here"
            >
                <IconLock className="shrink-0" />
                <span className="truncate">{label}</span>
            </Button>
            <FilterBarChipMenu nodeId={item.id} wrapType={wrapType} />
            <Button
                size="icon"
                variant="outline"
                aria-label={`Remove ${label} filter`}
                tooltip="Remove filter"
                onClick={() => removeItem(item.id)}
                data-attr="filter-bar-chip-remove"
            >
                <IconX />
            </Button>
        </ButtonGroup>
    )
}
