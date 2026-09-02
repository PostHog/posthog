import { useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import { TableOptionGroup } from './viewLinkLogic'

export interface TableComboboxProps {
    groups: TableOptionGroup[]
    value: string | null
    onChange: (value: string) => void
    placeholder?: string
    'aria-label': string
}

export function TableCombobox({
    groups,
    value,
    onChange,
    placeholder = 'Select a table',
    'aria-label': ariaLabel,
}: TableComboboxProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    return (
        <Combobox
            items={groups}
            value={value || null}
            onValueChange={(next: string | null) => {
                if (next) {
                    onChange(next)
                }
            }}
            open={open}
            onOpenChange={setOpen}
        >
            <ComboboxTrigger
                render={
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        // h-8 matches the LemonSelect/LemonSegmentedButton "small" height so the
                        // sentence controls line up.
                        className="h-8 max-w-80"
                        aria-label={ariaLabel}
                    >
                        <span className="min-w-0 truncate">{value || placeholder}</span>
                    </Button>
                }
            />
            <ComboboxContent anchor={triggerRef} side="bottom" sideOffset={6} className="min-w-[280px]">
                <ComboboxInput placeholder="Search tables..." />
                <ComboboxEmpty>No tables found.</ComboboxEmpty>
                <ComboboxList>
                    {(group: TableOptionGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            <ComboboxLabel>{group.value}</ComboboxLabel>
                            <ComboboxCollection>
                                {(tableName: string) => (
                                    <ComboboxItem key={tableName} value={tableName}>
                                        {tableName}
                                    </ComboboxItem>
                                )}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
