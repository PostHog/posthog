import { useState } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    useComboboxAnchor,
} from '@posthog/quill'

type TagsComboboxProps = {
    value: string[]
    onChange: (next: string[]) => void
    options?: string[]
    placeholder?: string
    autoFocus?: boolean
    disabled?: boolean
    /** When true (default), typing a value not in options surfaces a "Create X" entry. */
    allowCustomValues?: boolean
    /** Label used in the "Create X" placeholder, e.g. "tag" → "Create new tag "foo"". */
    customValueNoun?: string
    /** data-attr applied to the input */
    dataAttr?: string
    className?: string
}

/**
 * Multi-select tag/chip input on Quill's Combobox. Mirrors the storybook "Multiple" pattern.
 * Adds a synthetic "Create X" item when the typed input doesn't match any option — selecting it
 * commits the typed value via `onChange`.
 */
export function TagsCombobox(props: TagsComboboxProps): JSX.Element {
    return <TagsComboboxInner {...props} />
}

function TagsComboboxInner({
    value,
    onChange,
    options = [],
    placeholder,
    autoFocus,
    disabled,
    allowCustomValues = true,
    customValueNoun = 'tag',
    dataAttr,
    className,
}: TagsComboboxProps): JSX.Element {
    const [inputValue, setInputValue] = useState('')
    const trimmed = inputValue.trim()
    const showCreateItem =
        allowCustomValues && trimmed.length > 0 && !value.includes(trimmed) && !options.includes(trimmed)

    // Synthetic items list: existing options + (optionally) the "Create X" sentinel at the bottom.
    const items: string[] = [...options]
    const createSentinel = `__create__:${trimmed}`
    if (showCreateItem) {
        items.push(createSentinel)
    }

    return (
        <Combobox
            multiple
            autoHighlight
            items={items}
            value={value}
            onValueChange={(next: string[]) => {
                // Convert any sentinel selection into the real typed value, dedupe.
                const cleaned = (next ?? []).map((v) =>
                    v.startsWith('__create__:') ? v.slice('__create__:'.length) : v
                )
                onChange(Array.from(new Set(cleaned)))
                setInputValue('')
            }}
            inputValue={inputValue}
            onInputValueChange={(v: string) => setInputValue(v)}
        >
            <TagsComboboxBody
                placeholder={placeholder}
                autoFocus={autoFocus}
                disabled={disabled}
                dataAttr={dataAttr}
                className={className}
                createSentinel={showCreateItem ? createSentinel : null}
                customValueNoun={customValueNoun}
                trimmed={trimmed}
            />
        </Combobox>
    )
}

function TagsComboboxBody({
    placeholder,
    autoFocus,
    disabled,
    dataAttr,
    className,
    createSentinel,
    customValueNoun,
    trimmed,
}: {
    placeholder?: string
    autoFocus?: boolean
    disabled?: boolean
    dataAttr?: string
    className?: string
    createSentinel: string | null
    customValueNoun: string
    trimmed: string
}): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} className={className}>
                <ComboboxValue>
                    {(values) => (
                        <>
                            {(values as string[])
                                .filter((v) => !v.startsWith('__create__:'))
                                .map((v) => (
                                    <ComboboxChip key={v} title={v}>
                                        {v}
                                    </ComboboxChip>
                                ))}
                            <ComboboxChipsInput
                                placeholder={placeholder}
                                autoFocus={autoFocus}
                                disabled={disabled}
                                data-attr={dataAttr}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>
                    {trimmed ? `No matching ${customValueNoun}` : `No ${customValueNoun}s yet`}
                </ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => {
                        if (item === createSentinel) {
                            return (
                                <ComboboxItem key={item} value={item}>
                                    Create new {customValueNoun} "{trimmed}"
                                </ComboboxItem>
                            )
                        }
                        return (
                            <ComboboxItem key={item} value={item}>
                                {item}
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
