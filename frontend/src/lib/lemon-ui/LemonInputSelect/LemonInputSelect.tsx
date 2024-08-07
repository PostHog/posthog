import { Tooltip } from '@posthog/lemon-ui'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { range } from 'lib/utils'
import { useEffect, useMemo, useRef, useState } from 'react'

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
    ...props
}: LemonInputSelectProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false)
    const [inputValue, _setInputValue] = useState('')
    const popoverFocusRef = useRef<boolean>(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const values = value ?? []
    const altKeyHeld = useKeyHeld('Alt')

    const separateOnComma = allowCustomValues && mode === 'multiple'

    const visibleOptions = useMemo(() => {
        const res: LemonInputSelectOption[] = []
        const customValues = [...values]

        // We show the input value if custom values are allowed and it's not in the list
        if (allowCustomValues && inputValue && !values.includes(inputValue)) {
            customValues.unshift(inputValue.replace('\\,', ',')) // Transform escaped commas to plain commas
        }

        options.forEach((option) => {
            // Remove from the custom values list if it's in the options
            if (customValues.includes(option.key)) {
                customValues.splice(customValues.indexOf(option.key), 1)
            }

            // Check for filtering
            if (inputValue && !disableFiltering && !option.label.toLowerCase().includes(inputValue.toLowerCase())) {
                return
            }

            res.push(option)
        })

        // Custom values are always shown before the list
        if (customValues.length) {
            customValues.forEach((value) => {
                res.unshift({ key: value, label: value })
            })
        }

        // :HACKY: This is a quick fix to make the select dropdown work for large values,
        // as it was getting slow when we'd load more than ~10k entries. Ideally we'd
        // make this a virtualized list.
        return res.slice(0, 100)
    }, [options, inputValue, values])

    // Reset the selected index when the visible options change
    useEffect(() => {
        setSelectedIndex(0)
    }, [visibleOptions.length])

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

        _setInputValue(newValue)
        onInputChange?.(inputValue)
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

    const _onActionItem = (item: string): void => {
        if (altKeyHeld && allowCustomValues) {
            // In this case we want to remove it if added and set input to it
            if (values.includes(item)) {
                _removeItem(item)
            }
            setInputValue(item)
            return
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

    const prefix = useMemo(
        () => (
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
                                        <KeyboardShortcut option /> + click to edit
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
        ),
        [values, options, altKeyHeld, allowCustomValues]
    )

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
            overlay={
                <div className="space-y-px overflow-y-auto">
                    {title && <h5 className="mx-2 my-1">{title}</h5>}
                    {visibleOptions.length ? (
                        visibleOptions?.map((option, index) => {
                            const isHighlighted = index === selectedIndex
                            return (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    active={isHighlighted || values.includes(option.key)}
                                    onClick={() => _onActionItem(option.key)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                >
                                    <span className="flex-1 flex items-center justify-between gap-1">
                                        <span className="ph-no-capture">{option.labelComponent ?? option.label}</span>
                                        {isHighlighted ? (
                                            <span>
                                                <KeyboardShortcut enter />{' '}
                                                {altKeyHeld && allowCustomValues
                                                    ? 'edit'
                                                    : !values.includes(option.key)
                                                    ? mode === 'single'
                                                        ? 'select'
                                                        : 'add'
                                                    : mode === 'single'
                                                    ? 'unselect'
                                                    : 'remove'}
                                            </span>
                                        ) : undefined}
                                    </span>
                                </LemonButton>
                            )
                        })
                    ) : loading ? (
                        <>
                            {range(5).map((x) => (
                                <div key={x} className="flex gap-2 items-center h-10 px-1">
                                    <LemonSkeleton.Circle className="w-6 h-6" />
                                    <LemonSkeleton />
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
            <span className="LemonInputSelect" {...props}>
                <LemonInput
                    ref={inputRef}
                    placeholder={!values.length ? placeholder : undefined}
                    prefix={prefix}
                    onFocus={_onFocus}
                    onBlur={_onBlur}
                    value={inputValue}
                    onChange={setInputValue}
                    onKeyDown={_onKeyDown}
                    disabled={disabled}
                    autoFocus={autoFocus}
                />
            </span>
        </LemonDropdown>
    )
}
