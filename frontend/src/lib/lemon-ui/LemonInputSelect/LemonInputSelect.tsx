import { IconPencil } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import Fuse from 'fuse.js'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { range } from 'lib/utils'
import { MouseEvent, useEffect, useMemo, useRef, useState } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton } from '../LemonButton'
import { LemonDropdown } from '../LemonDropdown'
import { LemonInput, LemonInputProps } from '../LemonInput'
import { PopoverReferenceContext } from '../Popover'

const NON_ESCAPED_COMMA_REGEX = /(?<!\\),/

export interface LemonInputSelectOption {
    key: string
    label: string
    labelComponent?: React.ReactNode
    /** @internal */
    __isInput?: boolean
}

export type LemonInputSelectProps = Pick<
    // NOTE: We explicitly pick rather than omit to ensure these components aren't used incorrectly
    LemonInputProps,
    'autoFocus'
> & {
    options?: LemonInputSelectOption[]
    value?: string[] | null
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    /** Title shown at the top of the list. Looks the same as section titles in LemonMenu. */
    title?: string
    disableFiltering?: boolean
    mode: 'multiple' | 'single'
    allowCustomValues?: boolean
    onChange?: (newValue: string[]) => void
    onBlur?: () => void
    onFocus?: () => void
    onInputChange?: (newValue: string) => void
    'data-attr'?: string
    popoverClassName?: string
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    borderless?: boolean
    transparentBackground?: boolean
}

export function LemonInputSelect({
    placeholder,
    title,
    options = [],
    value,
    loading,
    onChange,
    onInputChange,
    onFocus,
    onBlur,
    mode,
    disabled,
    disableFiltering = false,
    allowCustomValues = false,
    autoFocus = false,
    popoverClassName,
    'data-attr': dataAttr,
    size = 'medium',
    borderless,
    transparentBackground,
}: LemonInputSelectProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false)
    const [inputValue, _setInputValue] = useState('')
    const popoverFocusRef = useRef<boolean>(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const values = value ?? []
    const altKeyHeld = useKeyHeld('Alt')

    const fuseRef = useRef<Fuse<LemonInputSelectOption>>(
        new Fuse(options, {
            keys: ['label', 'key'],
        })
    )

    const separateOnComma = allowCustomValues && mode === 'multiple'

    const allOptionsMap: Map<string, LemonInputSelectOption> = useMemo(() => {
        // Custom values are values that are not in the options list
        const customValues = values.filter((value) => !options.some((option) => option.key === value))
        // Custom values are shown as options before other options (Map guarantees preserves insertion order)
        const allOptionsMap = new Map<string, LemonInputSelectOption>()
        for (const customValue of customValues) {
            allOptionsMap.set(customValue, { key: customValue, label: customValue })
        }
        for (const option of options) {
            allOptionsMap.set(option.key, option)
        }
        // The below is a side effect (boo!) - but it's fine, since it's idempotent
        fuseRef.current.setCollection(Array.from(allOptionsMap.values()))
        return allOptionsMap
    }, [options, values])

    const visibleOptions = useMemo(() => {
        const ret: LemonInputSelectOption[] = []
        // Show the input value if custom values are allowed and it's not in the list
        if (inputValue && !values.includes(inputValue)) {
            if (allowCustomValues) {
                const unescapedInputValue = inputValue.replace('\\,', ',') // Transform escaped commas to plain commas
                ret.push({ key: unescapedInputValue, label: unescapedInputValue, __isInput: true })
            }
        } else if (mode === 'single' && values.length > 0) {
            // In single-select mode, show the selected value at the top
            ret.push(allOptionsMap.get(values[0]) ?? { key: values[0], label: values[0] })
        }

        let relevantOptions: LemonInputSelectOption[]
        if (!disableFiltering && inputValue) {
            // If filtering is enabled and there's input, perform fuzzy search…
            const results = fuseRef.current.search(inputValue)
            relevantOptions = results.map((result) => result.item)
        } else {
            // …otherwise show all options
            relevantOptions = Array.from(allOptionsMap.values())
        }
        for (const option of relevantOptions) {
            if (option.key === inputValue) {
                // We also don't want to show the input-based option again
                continue
            }
            if (mode === 'single' && values.length > 0 && option.key === values[0]) {
                // In single-select mode, we've already added the selected value to the top earlier
                continue
            }
            ret.push(option)
            if (ret.length >= 100) {
                // :HACKY: This is a quick fix to make the select dropdown work for large values, as it was getting slow when
                // we'd load more than ~10k entries. Ideally we'd make this a virtualized list.
                break
            }
        }

        return ret
    }, [allOptionsMap, allowCustomValues, inputValue, mode])

    // Reset the selected index when the visible options change
    useEffect(() => {
        setSelectedIndex(0)
    }, [visibleOptions.map((option) => option.key).join(':::')])

    const setInputValue = (newValue: string): void => {
        // Special case for multiple mode with custom values
        if (separateOnComma && newValue.match(NON_ESCAPED_COMMA_REGEX)) {
            const newValues = [...values]

            // We split on commas EXCEPT if they're escaped (to allow for commas in values)
            newValue.split(NON_ESCAPED_COMMA_REGEX).forEach((value) => {
                const trimmedValue = value.replace('\\,', ',').trim() // Transform escaped commas to plain commas
                if (trimmedValue && !values.includes(trimmedValue)) {
                    newValues.push(trimmedValue)
                }
            })

            onChange?.(newValues)
            newValue = ''
        }

        if (newValue) {
            // If popover was hidden due to Enter being pressed, but we kept input focus and now the user typed again,
            // we should show the popover again
            setShowPopover(true)
        }

        _setInputValue(newValue)
        onInputChange?.(newValue)
    }

    const _removeItem = (item: string): void => {
        let newValues = [...values]
        // Remove the item
        if (mode === 'single') {
            newValues = []
        } else {
            newValues.splice(values.indexOf(item), 1)
        }

        onChange?.(newValues)
    }

    const _addItem = (item: string): void => {
        let newValues = [...values]
        // Add the item
        if (mode === 'single') {
            newValues = [item]
        } else {
            if (!newValues.includes(item)) {
                newValues.push(item)
            }
        }

        setInputValue('')
        onChange?.(newValues)
    }

    const _onActionItem = (item: string, popoverOptionClickEvent?: MouseEvent): void => {
        if (altKeyHeld && allowCustomValues) {
            // In this case we want to remove it if added and set input to it
            if (values.includes(item)) {
                _removeItem(item)
            }
            _setInputValue(item)
            onInputChange?.(item)
            inputRef.current?.focus()
            return
        }
        if (mode === 'single') {
            setShowPopover(false)
            popoverFocusRef.current = false
            // Prevent propagating to Popover's onClickInside, which would set popoverFocusRef.current back to true
            popoverOptionClickEvent?.stopPropagation()
        }

        if (values.includes(item)) {
            _removeItem(item)
        } else {
            _addItem(item)
        }
    }

    const _onBlur = (): void => {
        // We need to add a delay as a click could be in the popover or the input wrapper which refocuses
        setTimeout(() => {
            if (popoverFocusRef.current) {
                popoverFocusRef.current = false
                inputRef.current?.focus()
                _onFocus()
                return
            }
            if (allowCustomValues && inputValue.trim() && !values.includes(inputValue)) {
                _onActionItem(inputValue.trim())
            } else {
                setInputValue('')
            }
            setShowPopover(false)
            onBlur?.()
        }, 100)
    }

    const _onFocus = (): void => {
        onFocus?.()
        setShowPopover(true)
        popoverFocusRef.current = true
    }

    const _onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Enter') {
            e.preventDefault()
            const itemToAdd = visibleOptions[selectedIndex]?.key

            if (itemToAdd) {
                _onActionItem(visibleOptions[selectedIndex]?.key)
            }
        } else if (e.key === 'Backspace') {
            if (!inputValue) {
                e.preventDefault()
                const newValues = [...values]
                newValues.pop()
                onChange?.(newValues)
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setSelectedIndex(Math.min(selectedIndex + 1, visibleOptions.length - 1))
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setSelectedIndex(Math.max(selectedIndex - 1, 0))
        }
    }

    const valuesPrefix = useMemo(() => {
        if (mode !== 'multiple' || values.length === 0) {
            return null // Not rendering values as a suffix in single-select mode, or if there are no values selected
        }

        return (
            // TRICKY: We don't want the popover to affect the snack buttons
            <PopoverReferenceContext.Provider value={null}>
                <>
                    {values.map((value) => {
                        const option = options.find((option) => option.key === value) ?? {
                            label: value,
                            labelComponent: null,
                        }
                        const snack = (
                            <LemonSnack
                                key={value}
                                title={option?.label}
                                onClose={() => _onActionItem(value)}
                                onClick={allowCustomValues ? () => _onActionItem(value) : undefined}
                            >
                                {option?.labelComponent ?? option?.label}
                            </LemonSnack>
                        )
                        return allowCustomValues ? (
                            <Tooltip
                                key={value}
                                title={
                                    <>
                                        Click to delete. Click with <KeyboardShortcut option /> to edit.
                                    </>
                                }
                            >
                                {snack}
                            </Tooltip>
                        ) : (
                            snack
                        )
                    })}
                </>
            </PopoverReferenceContext.Provider>
        )
    }, [allOptionsMap, altKeyHeld, allowCustomValues])

    const editButtonSuffix = useMemo(() => {
        if (mode === 'multiple' || !allowCustomValues || !values.length || inputValue) {
            // The edit button only applies to single-select mode with custom values allowed, when in no-input state
            return null
        }
        return (
            <PopoverReferenceContext.Provider value={null}>
                <LemonButton
                    icon={<IconPencil />}
                    onClick={() => {
                        setInputValue(values[0])
                        inputRef.current?.focus()
                        _onFocus()
                    }}
                    tooltip="Edit current value"
                    noPadding
                />
            </PopoverReferenceContext.Provider>
        )
    }, [mode, values, allowCustomValues, inputValue])

    return (
        <LemonDropdown
            matchWidth
            closeOnClickInside={false}
            actionable
            visible={showPopover}
            onClickOutside={() => {
                popoverFocusRef.current = false
                setShowPopover(false)
            }}
            onClickInside={(e) => {
                popoverFocusRef.current = true
                e.stopPropagation()
            }}
            className={popoverClassName}
            placement="bottom-start"
            fallbackPlacements={['bottom-end', 'top-start', 'top-end']}
            loadingBar={loading && visibleOptions.length > 0}
            overlay={
                <div className="space-y-px overflow-y-auto">
                    {title && <h5 className="mx-2 my-1">{title}</h5>}
                    {visibleOptions.length > 0 ? (
                        visibleOptions.map((option, index) => {
                            const isFocused = index === selectedIndex
                            const isSelected = values.includes(option.key)
                            return (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    active={isFocused || isSelected}
                                    onClick={(e) => _onActionItem(option.key, e)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                    icon={
                                        mode === 'multiple' && !option.__isInput ? (
                                            // No pointer events, since it's only for visual feedback
                                            <LemonCheckbox checked={isSelected} className="pointer-events-none" />
                                        ) : undefined
                                    }
                                    sideAction={{
                                        // To reduce visual clutter we only show the button for the focused item,
                                        // but we do want the side action present to make sure the layout is stable
                                        icon: isFocused ? <IconPencil /> : undefined,
                                        tooltip: (
                                            <>
                                                Edit this value <KeyboardShortcut option enter />
                                            </>
                                        ),
                                        onClick: () => {
                                            setInputValue(option.key)
                                            inputRef.current?.focus()
                                            _onFocus()
                                        },
                                    }}
                                >
                                    <span className="whitespace-nowrap ph-no-capture truncate">
                                        {!option.__isInput
                                            ? option.labelComponent ?? option.label // Regular option
                                            : mode === 'multiple'
                                            ? `Add "${option.key}"` // Input-based option
                                            : option.key}
                                    </span>
                                </LemonButton>
                            )
                        })
                    ) : loading ? (
                        <>
                            {range(5).map((x) => (
                                // 33px is the height of a regular list item
                                <div key={x} className="flex gap-2 items-center h-[33px] px-2">
                                    <LemonSkeleton.Circle className="size-[18px]" />
                                    <LemonSkeleton className="h-3.5 w-full" />
                                </div>
                            ))}
                        </>
                    ) : (
                        <p className="text-muted italic p-1">
                            {allowCustomValues
                                ? 'Start typing and press Enter to add options'
                                : `No options matching "${inputValue}"`}
                        </p>
                    )}
                </div>
            }
        >
            <LemonInput
                inputRef={inputRef}
                placeholder={
                    values.length === 0
                        ? placeholder
                        : mode === 'single'
                        ? allOptionsMap.get(values[0])?.label ?? values[0]
                        : allowCustomValues
                        ? 'Add value'
                        : 'Pick value'
                }
                prefix={valuesPrefix}
                suffix={editButtonSuffix}
                onFocus={_onFocus}
                onBlur={_onBlur}
                value={inputValue}
                onChange={setInputValue}
                onKeyDown={_onKeyDown}
                disabled={disabled}
                autoFocus={autoFocus}
                transparentBackground={transparentBackground}
                className={clsx(
                    'flex-wrap h-auto min-w-24',
                    // Putting button-like text styling on the single-select unfocused placeholder
                    mode === 'single' && values.length > 0 && 'placeholder:*:font-medium',
                    mode === 'single' &&
                        values.length > 0 &&
                        !showPopover &&
                        'cursor-pointer placeholder:*:text-default',
                    borderless && 'border-none'
                )}
                data-attr={dataAttr}
                size={size}
            />
        </LemonDropdown>
    )
}
