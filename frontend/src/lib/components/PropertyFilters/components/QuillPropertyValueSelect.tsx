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

const NON_ESCAPED_COMMA_REGEX = /(?<!\\),/
// Matches the Lemon input's cap, so a property with thousands of values stays quick to open and type into.
const MAX_LISTED_OPTIONS = 100
// An object, not a string, so no real property value can be mistaken for the "add what I typed" row.
const CREATE_ITEM = { create: true } as const
type Item = string | typeof CREATE_ITEM

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
    // Read when the menu closes, after Base UI has started clearing the input state.
    const latestInput = useRef('')
    latestInput.current = inputValue

    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    const typed = inputValue.trim()
    // Untrimmed, so a regex keeps significant spaces; PropertyValue trims for every other operator.
    const customValue = inputValue.replaceAll('\\,', ',')
    const showCreate = allowCustomValues && !!typed && !values.includes(typed) && !optionsByKey.has(typed)
    const query = typed.toLowerCase()
    const matches = (key: string): boolean => !query || key.toLowerCase().includes(query)
    const exactMatch = optionsByKey.has(typed) ? [typed] : []
    const optionKeys = options
        .map((option) => option.key)
        .filter((key) => key !== typed && matches(key))
        .slice(0, MAX_LISTED_OPTIONS - exactMatch.length)
    const selectedCustomKeys = values.filter((key) => !optionsByKey.has(key) && matches(key))
    const items: Item[] = [...(showCreate ? [CREATE_ITEM] : []), ...selectedCustomKeys, ...exactMatch, ...optionKeys]

    const resetInput = (): void => {
        setInputValue('')
        onInputChange('')
    }

    const commitValues = (keys: string[]): void => {
        if (multiple) {
            onChange(Array.from(new Set(keys)))
        } else {
            const added = keys.filter((key) => !values.includes(key))
            onChange(added.length ? [added[added.length - 1]] : keys.slice(-1))
            setOpen(false)
        }
        resetInput()
    }

    const changeInput = (next: string): void => {
        const transformed = inputTransform ? inputTransform(next) : next
        if (splitOnComma && NON_ESCAPED_COMMA_REGEX.test(transformed)) {
            const added = transformed
                .split(NON_ESCAPED_COMMA_REGEX)
                .map((part) => part.replaceAll('\\,', ',').trim())
                .filter((part) => part && !values.includes(part))
            onChange([...values, ...added])
            resetInput()
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
            filter={null}
            itemToStringLabel={(item: Item) => (typeof item === 'string' ? item : customValue)}
            value={values as Item[]}
            open={open}
            onOpenChange={(nextOpen, eventDetails) => {
                // Base UI clears the input as focus leaves, so what was typed is kept here rather than on blur.
                const pending = latestInput.current
                const leftField = eventDetails.reason === 'focus-out' || eventDetails.reason === 'outside-press'
                if (!nextOpen && leftField && allowCustomValues && pending.trim()) {
                    commitValues([...values, pending.replaceAll('\\,', ',')])
                }
                setOpen(nextOpen)
            }}
            inputValue={inputValue}
            onInputValueChange={changeInput}
            onValueChange={(next: Item[], eventDetails) => {
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                // In single-value mode, picking the selected row again keeps it; only its chip's remove button clears it.
                if (!multiple && eventDetails.reason === 'item-press' && next.length < values.length) {
                    setOpen(false)
                    resetInput()
                    return
                }
                commitValues(next.map((item) => (typeof item === 'string' ? item : customValue)))
            }}
        >
            <ComboboxChips ref={anchor} aria-invalid={invalid || undefined} className={className}>
                <ComboboxValue>
                    {(selected: Item[]) => (
                        <>
                            {(selected as string[]).map((key) => {
                                const tooltip = valueTooltip?.(key)
                                return tooltip ? (
                                    <Tooltip key={key}>
                                        <TooltipTrigger
                                            render={
                                                <ComboboxChip title={key}>
                                                    <span className="ph-no-capture">{key}</span>
                                                </ComboboxChip>
                                            }
                                        />
                                        <TooltipContent>{tooltip}</TooltipContent>
                                    </Tooltip>
                                ) : (
                                    <ComboboxChip key={key} title={key}>
                                        <span className="ph-no-capture">{key}</span>
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
                    {(item: Item) =>
                        typeof item !== 'string' ? (
                            <ComboboxItem key="create" value={item}>
                                <span className="ph-no-capture">{multiple ? `Add "${typed}"` : typed}</span>
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={item} value={item} tooltip={optionsByKey.get(item)?.tooltip}>
                                {optionsByKey.get(item)?.content ?? <span className="ph-no-capture">{item}</span>}
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
