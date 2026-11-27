import { useRef } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
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

    return (
        <Combobox<KeySelectOption>
            items={options}
            value={options.find((option) => option.value === value) ?? null}
            onValueChange={(next) => {
                if (next) {
                    onChange(next.value)
                }
            }}
            itemToStringLabel={(option) => option.value}
            itemToStringValue={(option) => option.value}
            isItemEqualToValue={(item, selected) => item.value === selected.value}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant="outline"
                        left
                        className="max-w-80"
                        disabledReason={disabledReason}
                        aria-label={ariaLabel}
                    />
                }
            >
                <span className="min-w-0 truncate">{value || 'Select a key'}</span>
            </ComboboxTrigger>
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
