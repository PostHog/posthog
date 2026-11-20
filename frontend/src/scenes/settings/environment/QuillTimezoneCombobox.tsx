import { useMemo } from 'react'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

export function QuillTimezoneCombobox({
    id,
    options,
    value,
    onChange,
    disabled,
    disabledReason,
}: {
    id?: string
    options: { key: string; label: string }[]
    value: string
    onChange: (timezone: string | undefined) => void
    disabled: boolean
    disabledReason?: string | null
}): JSX.Element {
    const labels = useMemo(() => new Map(options.map((option) => [option.key, option.label])), [options])
    const keys = useMemo(() => options.map((option) => option.key), [options])

    return (
        <Combobox<string>
            items={keys}
            value={value}
            onValueChange={(next) => onChange(next ?? undefined)}
            itemToStringLabel={(key: string) => labels.get(key) ?? key}
            disabled={disabled}
        >
            <ComboboxInput
                id={id}
                className="w-full max-w-160"
                placeholder="Select a time zone"
                disabled={disabled}
                disabledReason={disabledReason}
                data-attr="timezone-select"
            />
            <ComboboxContent>
                <ComboboxEmpty>No matching time zones</ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key}>
                            {labels.get(key) ?? key}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
