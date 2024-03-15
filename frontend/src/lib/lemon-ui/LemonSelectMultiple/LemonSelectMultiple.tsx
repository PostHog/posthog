import './LemonSelectMultiple.scss'

import { IconCheck } from '@posthog/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { range } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '../LemonButton'
import { LemonDropdown } from '../LemonDropdown'
import { LemonInput } from '../LemonInput'

export interface LemonSelectMultipleOption {
    label: string
    labelComponent?: React.ReactNode
}

export interface LemonSelectMultipleOptionItem extends LemonSelectMultipleOption {
    key: string
}

export type LemonSelectMultipleOptions = Record<string, LemonSelectMultipleOption>

export type LemonSelectMultipleProps = {
    selectClassName?: string // TODO: Find use cases of this and remove it or fix it
    options?: LemonSelectMultipleOptions | LemonSelectMultipleOptionItem[] // TOOD: Make this array only?
    value?: string[] | null
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    onBlur?: () => void
    filterOptions?: boolean
    mode?: 'single' | 'multiple' | 'multiple-custom'
    onChange?: (newValue: string[]) => void
    'data-attr'?: string
}

export function LemonSelectMultiple({
    placeholder,
    options,
    value,
    loading,
    onChange,
    mode,
    disabled,
    filterOptions = true,
    ...props
}: LemonSelectMultipleProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false)
    const [inputValue, setInputValue] = useState('')
    const popoverFocusRef = useRef<boolean>(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedIndex, setSelectedIndex] = useState(0)

    const optionsAsList: LemonSelectMultipleOptionItem[] = Array.isArray(options)
        ? options
        : Object.entries(options || {}).map(([key, option]) => ({
              key: key,
              ...option,
          }))

    // TODO: Derive selected as part of the optionsList
    const values = value ?? []

    const filteredOptions =
        inputValue && filterOptions
            ? optionsAsList?.filter((option) => {
                  return option.label.toLowerCase().includes(inputValue.toLowerCase())
              })
            : optionsAsList

    const customValues = values.filter((value) => !optionsAsList.find((option) => option.key === value))

    if (customValues.length) {
        customValues.forEach((value) => {
            filteredOptions.unshift({ key: value, label: value })
        })
    }

    if (mode === 'multiple-custom' && inputValue && !values.includes(inputValue)) {
        filteredOptions.unshift({ key: inputValue, label: inputValue })
    }

    useEffect(() => {
        if (selectedIndex >= filteredOptions.length) {
            setSelectedIndex(Math.max(0, filteredOptions.length - 1))
        }
    }, [filteredOptions.length])

    const _onActionItem = (item: string): void => {
        let newValues = [...values]
        if (values.includes(item)) {
            if (mode === 'single') {
                newValues = []
            } else {
                newValues.splice(values.indexOf(item), 1)
            }
        } else {
            // Add the item
            if (mode === 'single') {
                newValues = [item]
            } else {
                newValues.push(item)
            }

            setInputValue('')
        }

        onChange?.(newValues)
    }

    const _onBlur = (): void => {
        // We ned to add a delay as a click could be in the popover or the input wrapper which refocuses
        setTimeout(() => {
            if (popoverFocusRef.current) {
                popoverFocusRef.current = false
                inputRef.current?.focus()
                _onFocus()
                return
            }
            if (mode === 'multiple-custom' && inputValue.trim() && !values.includes(inputValue)) {
                _onActionItem(inputValue.trim())
            } else {
                setInputValue('')
            }
            setShowPopover(false)
        }, 100)
    }

    const _onFocus = (): void => {
        setShowPopover(true)
        popoverFocusRef.current = true
    }

    const _onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Enter') {
            e.preventDefault()

            const itemToAdd = filteredOptions[selectedIndex]?.key
            if (itemToAdd) {
                _onActionItem(filteredOptions[selectedIndex]?.key)
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
            setSelectedIndex(Math.min(selectedIndex + 1, optionsAsList.length - 1))
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setSelectedIndex(Math.max(selectedIndex - 1, 0))
        }
    }

    const prefix = (
        <>
            {values.map((value) => {
                const option = optionsAsList.find((option) => option.key === value) ?? {
                    label: value,
                    labelComponent: null,
                }
                return (
                    <>
                        <LemonSnack title={option?.label} onClose={() => _onActionItem(value)}>
                            {option?.labelComponent ?? option?.label}
                        </LemonSnack>
                    </>
                )
            })}
        </>
    )

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            sameWidth
            actionable
            onClickOutside={() => {
                popoverFocusRef.current = false
                setShowPopover(false)
            }}
            onClickInside={(e) => {
                popoverFocusRef.current = true
                e.stopPropagation()
            }}
            overlay={
                <div className="space-y-px overflow-y-auto">
                    {filteredOptions.length ? (
                        filteredOptions?.map((option, index) => {
                            return (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    active={index === selectedIndex}
                                    sideIcon={values.includes(option.key) ? <IconCheck /> : undefined}
                                    onClick={() => _onActionItem(option.key)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                >
                                    <span>{option.labelComponent ?? option.label}</span>
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
                            {mode === 'multiple-custom'
                                ? 'Start typing and press Enter to add options'
                                : `No options matching "${inputValue}"`}
                        </p>
                    )}
                </div>
            }
        >
            <span>
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
                />
            </span>
        </LemonDropdown>
    )
}
