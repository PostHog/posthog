import { useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
} from '@posthog/quill'

import type { SavedFilter } from '../../dashboard/document/dashboardTypes'
import type { FilterDefinition } from '../filterDefinition'
import { hasFilterOn } from '../filterSpec'

export function AddFilterMenu({
    filters,
    types,
    onAdd,
}: {
    filters: SavedFilter[]
    types: FilterDefinition[]
    onAdd: (filter: Omit<SavedFilter, 'id'>) => void
}): JSX.Element | null {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [picking, setPicking] = useState<FilterDefinition | null>(null)
    const items = types.flatMap(({ type, addFilterOptions }) => addFilterOptions.map((item) => ({ type, ...item })))
    const pickers = types.filter((type) => type.Picker && type.pickerLabel)
    if (items.length === 0 && pickers.length === 0) {
        return null
    }
    const disabledReason = (filter: Omit<SavedFilter, 'id'>): string | undefined =>
        hasFilterOn(filters, filter, types) ? 'Already added' : undefined
    const Picker = picking?.Picker
    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button ref={triggerRef} size="sm" variant="default" data-attr="dashboard-v2-add-filter" />}
                >
                    <IconPlus />
                    Filter
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Add a filter</DropdownMenuLabel>
                        {items.map(({ type, label, create }) => {
                            const filter = create()
                            return (
                                <DropdownMenuItem
                                    key={`${type}-${label}`}
                                    disabledReason={disabledReason(filter)}
                                    onClick={() => onAdd(filter)}
                                >
                                    {label}
                                </DropdownMenuItem>
                            )
                        })}
                    </DropdownMenuGroup>
                    {pickers.length > 0 && items.length > 0 && <DropdownMenuSeparator />}
                    {pickers.map((type) => (
                        <DropdownMenuItem
                            key={`${type.type}-picker`}
                            data-attr="dashboard-v2-add-filter-picker"
                            onClick={() => setPicking(type)}
                        >
                            {type.pickerLabel}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
            <Popover open={!!Picker} onOpenChange={(open) => !open && setPicking(null)}>
                <PopoverContent anchor={triggerRef} align="start" className="w-auto p-0">
                    {Picker && (
                        <Picker
                            onPick={(filter) => {
                                setPicking(null)
                                if (!disabledReason(filter)) {
                                    onAdd(filter)
                                }
                            }}
                            onClose={() => setPicking(null)}
                        />
                    )}
                </PopoverContent>
            </Popover>
        </>
    )
}
