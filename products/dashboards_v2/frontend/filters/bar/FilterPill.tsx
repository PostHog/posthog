import { IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import type { SavedFilter } from '../../dashboard/document/dashboardTypes'
import type { FilterDefinition } from '../filterDefinition'
import { findFilterType } from '../filterSpec'

export type FilterPillProps = {
    filter: SavedFilter
    /** The kinds of filter the page supports. A filter of any other kind shows that it can't be used here. */
    types: FilterDefinition[]
    value: unknown
    onChange: (value: unknown) => void
    onRemove?: () => void
    defaultOpen?: boolean
}

export function FilterPill({ filter, types, value, onChange, onRemove, defaultOpen }: FilterPillProps): JSX.Element {
    const definition = findFilterType(types, filter.type)
    // A dashed outline marks a filter that has no value yet, so it does not narrow the panels.
    return (
        <ButtonGroup className={value === undefined ? '[&_button]:border-dashed' : undefined}>
            {definition ? (
                <definition.Control filter={filter} value={value} onChange={onChange} defaultOpen={defaultOpen} />
            ) : (
                <Button size="sm" variant="outline" disabledReason="This page can't use this kind of filter">
                    {filter.label ?? filter.type}
                </Button>
            )}
            {onRemove && (
                <Button
                    size="icon-sm"
                    variant="outline"
                    aria-label="Remove filter"
                    tooltip="Remove filter"
                    data-attr="dashboard-v2-remove-filter"
                    onClick={onRemove}
                >
                    <IconX />
                </Button>
            )}
        </ButtonGroup>
    )
}
