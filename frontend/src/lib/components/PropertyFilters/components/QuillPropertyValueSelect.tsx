import { ReactNode, useRef, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    MenuLabel,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

const CREATE_PREFIX = '__create__:'
const NON_ESCAPED_COMMA_REGEX = /(?<!\\),/

export interface QuillPropertyValueOption {
    key: string
    content: ReactNode
    tooltip?: ReactNode
}

interface QuillPropertyValueSelectProps {
    values: string[]
    options: QuillPropertyValueOption[]
    multiple: boolean
    allowCustomValues: boolean
    loading: boolean
    onChange: (keys: string[]) => void
    onInputChange: (input: string) => void
    inputTransform?: (input: string) => string
    splitOnComma: boolean
    placeholder?: string
    invalid: boolean
    suggestionsLabel?: string | null
    onRefresh?: () => void
    refreshDisabledReason?: string
    valueTooltip?: (key: string) => ReactNode
    autoFocus?: boolean
    className?: string
}

export function QuillPropertyValueSelect({
    values,
    options,
    multiple,
    allowCustomValues,
    loading,
    onChange,
    onInputChange,
    inputTransform,
    splitOnComma,
    placeholder,
    invalid,
    suggestionsLabel,
    onRefresh,
    refreshDisabledReason,
    valueTooltip,
    autoFocus,
    className,
}: QuillPropertyValueSelectProps): JSX.Element {
    const [inputValue, setInputValue] = useState('')
    const [open, setOpen] = useState(false)
    const anchor = useRef<HTMLDivElement>(null)

    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    const typed = inputValue.trim()
    const createKey =
        allowCustomValues && typed && !values.includes(typed) && !optionsByKey.has(typed) ? CREATE_PREFIX + typed : null
    const selectedCustomKeys = values.filter((key) => !optionsByKey.has(key))
    const items = [...(createKey ? [createKey] : []), ...selectedCustomKeys, ...options.map((option) => option.key)]

    const changeInput = (next: string): void => {
        const transformed = inputTransform ? inputTransform(next) : next
        if (splitOnComma && NON_ESCAPED_COMMA_REGEX.test(transformed)) {
            const added = transformed
                .split(NON_ESCAPED_COMMA_REGEX)
                .map((part) => part.replaceAll('\\,', ',').trim())
                .filter((part) => part && !values.includes(part))
            onChange([...values, ...added])
            setInputValue('')
            onInputChange('')
            return
        }
        setInputValue(transformed)
        onInputChange(transformed)
    }

    return (
        <Combobox
            multiple
            autoHighlight
            items={items}
            value={values}
            open={open}
            onOpenChange={setOpen}
            inputValue={inputValue}
            onInputValueChange={changeInput}
            onValueChange={(next: string[], eventDetails) => {
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                const keys = next.map((key) => (key.startsWith(CREATE_PREFIX) ? key.slice(CREATE_PREFIX.length) : key))
                if (multiple) {
                    onChange(Array.from(new Set(keys)))
                } else {
                    const added = keys.filter((key) => !values.includes(key))
                    onChange(added.length ? [added[added.length - 1]] : keys.slice(-1))
                    setOpen(false)
                }
                setInputValue('')
                onInputChange('')
            }}
        >
            <ComboboxChips ref={anchor} aria-invalid={invalid || undefined} className={className}>
                <ComboboxValue>
                    {(selected: string[]) => (
                        <>
                            {selected.map((key) => {
                                const tooltip = valueTooltip?.(key)
                                return tooltip ? (
                                    <Tooltip key={key}>
                                        <TooltipTrigger render={<ComboboxChip title={key}>{key}</ComboboxChip>} />
                                        <TooltipContent>{tooltip}</TooltipContent>
                                    </Tooltip>
                                ) : (
                                    <ComboboxChip key={key} title={key}>
                                        {key}
                                    </ComboboxChip>
                                )
                            })}
                            <ComboboxChipsInput
                                placeholder={selected.length && !multiple ? undefined : placeholder}
                                autoFocus={autoFocus}
                                data-attr="prop-val"
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor} className="max-w-200">
                {suggestionsLabel && (
                    <MenuLabel className="flex items-center justify-between gap-4">
                        {suggestionsLabel}
                        {onRefresh && (
                            <Button
                                size="icon-xs"
                                aria-label="Refresh values"
                                tooltip="Refresh values"
                                disabledReason={refreshDisabledReason}
                                onClick={onRefresh}
                            >
                                {loading ? <Spinner /> : <IconRefresh />}
                            </Button>
                        )}
                    </MenuLabel>
                )}
                <ComboboxEmpty>
                    {loading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading values…
                        </span>
                    ) : (
                        'No matching values'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) =>
                        key === createKey ? (
                            <ComboboxItem key={key} value={key}>
                                {multiple ? `Add "${typed}"` : typed}
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={key} value={key} tooltip={optionsByKey.get(key)?.tooltip}>
                                {optionsByKey.get(key)?.content ?? key}
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
