import { useId, useMemo, useState } from 'react'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

export interface QuillMappingOption {
    key: string
    label: string
}

/** Single-value combobox that also accepts a typed value that is not in the options. */
export function QuillMappingCombobox({
    value,
    onChange,
    options,
    placeholder,
    loading,
    disabledReason,
    ariaLabel,
    className,
}: {
    value: string | null
    onChange: (value: string | null) => void
    options: QuillMappingOption[]
    placeholder: string
    loading?: boolean
    disabledReason?: string | null
    ariaLabel?: string
    className?: string
}): JSX.Element {
    const [inputValue, setInputValue] = useState('')
    const customPrefix = `__custom__${useId()}:`
    const labels = useMemo(() => new Map(options.map((option) => [option.key, option.label])), [options])

    const trimmed = inputValue.trim()
    const customSentinel = `${customPrefix}${trimmed}`
    const showCustomItem = !loading && trimmed.length > 0 && !labels.has(trimmed) && trimmed !== value

    const items = options.map((option) => option.key)
    if (value && !labels.has(value)) {
        items.unshift(value)
    }
    if (showCustomItem) {
        items.push(customSentinel)
    }

    function labelFor(key: string): string {
        return key === customSentinel ? trimmed : (labels.get(key) ?? key)
    }

    return (
        <Combobox<string>
            items={items}
            value={value}
            onValueChange={(next) => onChange(next === customSentinel ? trimmed : next)}
            onInputValueChange={(next: string) => setInputValue(next)}
            itemToStringLabel={labelFor}
        >
            <ComboboxInput
                className={className}
                placeholder={loading ? 'Loading...' : placeholder}
                aria-label={ariaLabel}
                disabledReason={disabledReason}
            />
            <ComboboxContent>
                <ComboboxEmpty>{loading ? 'Loading...' : 'Type a value to use it'}</ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key}>
                            {key === customSentinel ? `Use "${trimmed}"` : labelFor(key)}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
