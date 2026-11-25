import { useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    SelectTriggerIcon,
} from '@posthog/quill'

import { KeySelectOption } from '../logics/viewLinkLogic'

export interface QuillJoinKeyColumnComboboxProps {
    options: KeySelectOption[]
    value: string | null
    onChange: (key: string) => void
    disabledReason?: string
    'aria-label': string
}

export function QuillJoinKeyColumnCombobox({
    options,
    value,
    onChange,
    disabledReason,
    'aria-label': ariaLabel,
}: QuillJoinKeyColumnComboboxProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    return (
        <Combobox<KeySelectOption>
            items={options}
            value={options.find((option) => option.value === value) ?? null}
            onValueChange={(next) => {
                if (next) {
                    onChange(next.value)
                }
                setOpen(false)
            }}
            open={open}
            onOpenChange={setOpen}
            itemToStringLabel={(option) => option.value}
            itemToStringValue={(option) => option.value}
            isItemEqualToValue={(item, selected) => item.value === selected.value}
        >
            <Button
                ref={triggerRef}
                variant="outline"
                left
                className="max-w-80"
                onClick={() => setOpen(!open)}
                disabledReason={disabledReason}
                aria-label={ariaLabel}
            >
                <span className="min-w-0 truncate">{value || 'Select a key'}</span>
                <SelectTriggerIcon />
            </Button>
            <ComboboxContent anchor={triggerRef} className="min-w-60">
                <ComboboxInput placeholder="Search columns..." showTrigger={false} />
                <ComboboxEmpty>No results</ComboboxEmpty>
                <ComboboxList>
                    {(option: KeySelectOption) => (
                        <ComboboxItem key={option.value} value={option} disabledReason={option.disabledReason}>
                            {option.label}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
