import { IconPencil } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import Fuse from 'fuse.js'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { range } from 'lib/utils'
import { MouseEvent, useEffect, useMemo, useRef, useState } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton, LemonButtonPropsBase, SideAction } from '../LemonButton'
import { LemonDropdown } from '../LemonDropdown'
import { LemonInput, LemonInputProps } from '../LemonInput'
import { PopoverReferenceContext } from '../Popover'
import { TooltipTitle } from '../Tooltip/Tooltip'

const NON_ESCAPED_COMMA_REGEX = /(?<!\\),/

export interface LemonInputSelectOption {
    key: string
    label: string
    labelComponent?: React.ReactNode
    tooltip?: TooltipTitle
    /** @internal */
    __isInput?: boolean
}

export type LemonInputSelectAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export type LemonInputSelectProps = Pick<
    // NOTE: We explicitly pick rather than omit to ensure these components aren't used incorrectly
    LemonInputProps,
    'autoFocus' | 'autoWidth' | 'fullWidth'
> & {
    options?: LemonInputSelectOption[]
    value?: string[] | null
    limit?: number // Limit the number of options to show
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    title?: string // Title shown at the top of the list. Looks the same as section titles in LemonMenu.
    disableFiltering?: boolean
    disablePrompting?: boolean
    mode: 'multiple' | 'single'
    allowCustomValues?: boolean
    emptyStateComponent?: React.ReactNode
    onChange?: (newValue: string[]) => void
    onBlur?: () => void
    onFocus?: () => void
    onInputChange?: (newValue: string) => void
    'data-attr'?: string
    className?: string
    popoverClassName?: string
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    transparentBackground?: boolean
    displayMode?: 'snacks' | 'count'
    bulkActions?: 'clear-all' | 'select-and-clear-all'
    action?: LemonInputSelectAction
}

export function LemonInputSelect({
    placeholder,
    title,
    options = [],
    value,
    limit = Number.POSITIVE_INFINITY,
    loading,
    emptyStateComponent,
    onChange,
    onInputChange,
    onFocus,
    onBlur,
    mode,
    disabled,
    disableFiltering = false,
    disablePrompting = false,
    allowCustomValues = false,
    autoFocus = false,
    className,
    popoverClassName,
    'data-attr': dataAttr,
    size = 'medium',
    transparentBackground,
    autoWidth = true,
    fullWidth = false,
    displayMode = 'snacks',
    bulkActions,
    action,
}: LemonInputSelectProps): JSX.Element {
    const [showPopover, setShowPopover] = useState(false)
    const [inputValue, _setInputValue] = useState('')
    const [itemBeingEditedIndex, setItemBeingEditedIndex] = useState<number | null>(null)
    const popoverFocusRef = useRef<boolean>(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [selectedIndex, setSelectedIndex] = useState(0)
    const values = value ? value.slice() : []
    if (itemBeingEditedIndex !== null) {
        // If we're editing an item, we don't want it to be in the values list - it's ephemeral in that state
        values.splice(itemBeingEditedIndex, 1)
    }

    const fuseRef = useRef<Fuse<LemonInputSelectOption>>(
        new Fuse(options, {
            keys: ['label', 'key'],
        })
    )

    const separateOnComma = allowCustomValues && mode === 'multiple'

    // We stringify the objects to prevent wasteful recalculations (esp. Fuse). Note: labelComponent is not serializable
    const optionsKey = JSON.stringify(options, (key, value) => (key === 'labelComponent' ? value?.name : value))
    const valuesKey = JSON.stringify(values)
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
    }, [optionsKey, valuesKey])

    const visibleOptions = useMemo(() => {
        const ret: LemonInputSelectOption[] = []
        // Show the input value if custom values are allowed and it's not in the list
        if (inputValue && !values.includes(inputValue)) {
            if (allowCustomValues) {
                const unescapedInputValue = inputValue.replaceAll('\\,', ',') // Transform escaped commas to plain commas
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
                const trimmedValue = value.replaceAll('\\,', ',').trim() // Transform escaped commas to plain commas
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

    const _removeItem = (item: string, currentValues: string[] = values): void => {
        // Remove the item
        if (mode === 'single') {
            onChange?.([])
            return
        }
        const newValues = currentValues.slice()
        newValues.splice(newValues.indexOf(item), 1)
        onChange?.(newValues)
    }

    const _addItem = (item: string, atIndex?: number | null, currentValues: string[] = values): void => {
        setInputValue('')
        if (mode === 'single') {
            onChange?.([item])
            return
        }
        const newValues = currentValues.slice()
        if (!newValues.includes(item)) {
            if (atIndex != undefined) {
                newValues.splice(atIndex, 0, item)
            } else {
                newValues.push(item)
            }
        }
        onChange?.(newValues)
    }

    const _onActionItem = (
        item: string,
        popoverOptionClickEvent: MouseEvent | null,
        shouldInitiateEdit?: boolean
    ): void => {
        if (shouldInitiateEdit && allowCustomValues) {
            // In this case we want to remove it if added and set input to it
            let indexOfValue = values.indexOf(item)
            if (indexOfValue > -1) {
                if (itemBeingEditedIndex !== null && itemBeingEditedIndex < indexOfValue) {
                    // If already editing an item that's earlier in the list the the one we're about to edit,
                    // we need to adjust the index by 1
                    indexOfValue += 1
                }
                setItemBeingEditedIndex(indexOfValue)
            }
            _setInputValue(item)
            onInputChange?.(item)
            inputRef.current?.focus()
            return
        }
        setItemBeingEditedIndex(null)
        if (mode === 'single') {
            setShowPopover(false)
            popoverFocusRef.current = false
            // Prevent propagating to Popover's onClickInside, which would set popoverFocusRef.current back to true
            popoverOptionClickEvent?.stopPropagation()
        }

        if (values.includes(item)) {
            _removeItem(item)
        } else {
            _addItem(item, itemBeingEditedIndex)
        }
    }

    const _onBlur = (): void => {
        const hasSelectedAutofilledValue = selectedIndex > 0
        const hasCustomValue =
            !hasSelectedAutofilledValue && allowCustomValues && inputValue.trim() && !values.includes(inputValue)
        if (popoverFocusRef.current) {
            popoverFocusRef.current = false
            inputRef.current?.focus()
            _onFocus()
            if (hasCustomValue) {
                _onActionItem(inputValue.trim(), null)
            }
            return
        }
        if (hasCustomValue) {
            _onActionItem(inputValue.trim(), null)
        } else {
            setInputValue('')
        }
        setShowPopover(false)
        onBlur?.()
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
                _onActionItem(visibleOptions[selectedIndex]?.key, null)
            }
            e.currentTarget.blur()
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
        if (mode !== 'multiple' || values.length === 0 || displayMode !== 'snacks') {
            return null
        }

        const preInputValues = itemBeingEditedIndex !== null ? values.slice(0, itemBeingEditedIndex) : values

        // TRICKY: We don't want the popover to affect the snack buttons
        return (
            <PopoverReferenceContext.Provider value={null}>
                <ValueSnacks
                    values={preInputValues}
                    options={options}
                    onClose={(value) => _onActionItem(value, null)}
                    onInitiateEdit={allowCustomValues ? (value) => _onActionItem(value, null, true) : null}
                />
            </PopoverReferenceContext.Provider>
        )
    }, [allOptionsMap, allowCustomValues, itemBeingEditedIndex])

    const valuesAndEditButtonSuffix = useMemo(() => {
        // The edit button only applies to single-select mode with custom values allowed, when in no-input state
        const isEditButtonVisible = mode !== 'multiple' && allowCustomValues && values.length && !inputValue

        const postInputValues =
            displayMode === 'snacks' && itemBeingEditedIndex !== null ? values.slice(itemBeingEditedIndex) : []

        if (!isEditButtonVisible && postInputValues.length === 0) {
            return null
        }

        return (
            <PopoverReferenceContext.Provider value={null}>
                <ValueSnacks
                    values={postInputValues}
                    options={options}
                    onClose={(value) => _onActionItem(value, null)}
                    onInitiateEdit={allowCustomValues ? (value) => _onActionItem(value, null, true) : null}
                />
                {isEditButtonVisible && (
                    <div className="grow flex flex-col items-end">
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
                    </div>
                )}
            </PopoverReferenceContext.Provider>
        )
    }, [mode, values, allowCustomValues, itemBeingEditedIndex, inputValue])

    // Positioned like a placeholder but rendered via the suffix since the actual placeholder has to be a string
    const countPlaceholder = useMemo(() => {
        if (displayMode !== 'count' || mode !== 'multiple' || inputValue || loading) {
            return null
        }
        return values.length === 0 ? (
            <span className="-ml-2 text-muted">Select from {options.length} options</span>
        ) : (
            <span className="-ml-2">
                {values.length === options.length
                    ? `All ${options.length} selected`
                    : `${values.length}/${options.length} selected`}
            </span>
        )
    }, [displayMode, mode, inputValue, loading, values.length, options.length])

    const wasLimitReached = values.length >= limit

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
                <div className="deprecated-space-y-px overflow-y-auto">
                    {title && <h5 className="mx-2 my-1">{title}</h5>}

                    {bulkActions && mode === 'multiple' && (
                        <div className="flex items-center mb-0.5" onMouseEnter={() => setSelectedIndex(-1)}>
                            {bulkActions === 'select-and-clear-all' && (
                                <LemonButton
                                    size="small"
                                    className="flex-1"
                                    disabledReason={
                                        values.length === allOptionsMap.size
                                            ? 'All options are already selected'
                                            : undefined
                                    }
                                    tooltipPlacement="top-start"
                                    tooltipArrowOffset={50}
                                    onClick={() => onChange?.(Array.from(allOptionsMap.keys()))}
                                    icon={
                                        <LemonCheckbox
                                            checked={
                                                values.length === allOptionsMap.size
                                                    ? true
                                                    : values.length
                                                    ? 'indeterminate'
                                                    : false
                                            }
                                            className="pointer-events-none"
                                        />
                                    }
                                >
                                    Select all
                                </LemonButton>
                            )}
                            <LemonButton
                                size="small"
                                className={clsx({ 'flex-1': bulkActions === 'clear-all' })}
                                tooltipPlacement={bulkActions === 'select-and-clear-all' ? 'top-end' : 'top-start'}
                                tooltipArrowOffset={bulkActions === 'clear-all' ? 30 : undefined}
                                disabledReason={values.length === 0 ? 'No options are selected' : undefined}
                                onClick={() => onChange?.([])}
                            >
                                Clear all
                            </LemonButton>
                        </div>
                    )}

                    {action && (
                        <div className="flex items-center mb-0.5" onMouseEnter={() => setSelectedIndex(-1)}>
                            <LemonButton
                                size="small"
                                className="flex-1"
                                disabledReason={action?.disabledReason}
                                onClick={action?.onClick}
                            >
                                {action?.children}
                            </LemonButton>
                        </div>
                    )}

                    {visibleOptions.length > 0 ? (
                        visibleOptions.map((option, index) => {
                            const isFocused = index === selectedIndex
                            const isSelected = values.includes(option.key)
                            const isDisabled = wasLimitReached && !isSelected
                            return (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    active={isFocused}
                                    onClick={(e) => !isDisabled && _onActionItem(option.key, e)}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                    disabledReason={isDisabled ? `Limit of ${limit} options reached` : undefined}
                                    tooltip={option.tooltip}
                                    icon={
                                        mode === 'multiple' && !option.__isInput ? (
                                            // No pointer events, since it's only for visual feedback
                                            <LemonCheckbox checked={isSelected} className="pointer-events-none" />
                                        ) : undefined
                                    }
                                    sideAction={
                                        !option.__isInput && allowCustomValues
                                            ? {
                                                  // To reduce visual clutter we only show the icon on focus or hover,
                                                  // but we do want it present to make sure the layout is stable
                                                  icon: <IconPencil className={!isFocused ? 'invisible' : undefined} />,
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
                                              }
                                            : undefined
                                    }
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
                        <>
                            {emptyStateComponent ? (
                                emptyStateComponent
                            ) : (
                                <p className="text-secondary italic p-1">
                                    {allowCustomValues
                                        ? 'Start typing and press Enter to add options'
                                        : `No options matching "${inputValue}"`}
                                </p>
                            )}
                        </>
                    )}
                </div>
            }
        >
            <LemonInput
                inputRef={inputRef}
                placeholder={
                    displayMode === 'count'
                        ? undefined
                        : values.length === 0
                        ? placeholder
                        : mode === 'single'
                        ? allOptionsMap.get(values[0])?.label ?? values[0]
                        : allowCustomValues
                        ? 'Add value'
                        : disablePrompting
                        ? undefined
                        : 'Pick value'
                }
                autoWidth={autoWidth}
                fullWidth={fullWidth}
                prefix={valuesPrefix}
                suffix={
                    <>
                        {countPlaceholder}
                        {valuesAndEditButtonSuffix}
                    </>
                }
                onFocus={_onFocus}
                onBlur={_onBlur}
                value={inputValue}
                onChange={setInputValue}
                onKeyDown={_onKeyDown}
                disabled={disabled}
                autoFocus={autoFocus}
                transparentBackground={transparentBackground}
                className={clsx(
                    '!h-auto leading-7', // leading-7 means line height aligned with LemonSnack height
                    // Putting button-like text styling on the single-select unfocused placeholder
                    // NOTE: We need font-medium on both the input (for autosizing) and its placeholder (for display)
                    mode === 'multiple' && 'flex-wrap',
                    mode === 'single' && values.length > 0 && '*:*:font-medium *:*:placeholder:font-medium',
                    mode === 'single' && values.length > 0 && !showPopover && '*:*:placeholder:text-default',
                    className
                )}
                data-attr={dataAttr}
                size={size}
            />
        </LemonDropdown>
    )
}

function ValueSnacks({
    values,
    options,
    onClose,
    onInitiateEdit,
}: {
    values: string[]
    options: LemonInputSelectOption[]
    onClose: (value: string) => void
    onInitiateEdit: ((value: string) => void) | null
}): JSX.Element {
    return (
        <>
            {values.map((value) => {
                const option = options.find((option) => option.key === value) ?? {
                    label: value,
                    labelComponent: null,
                }
                return (
                    <Tooltip
                        key={value}
                        title={
                            <>
                                <span>
                                    {onInitiateEdit && (
                                        <>
                                            Click on the text to edit.
                                            <br />
                                        </>
                                    )}
                                </span>
                                <span>Click on the X to remove.</span>
                            </>
                        }
                    >
                        <LemonSnack
                            title={option?.label}
                            onClose={() => onClose(value)}
                            onClick={onInitiateEdit ? () => onInitiateEdit(value) : undefined}
                            className="cursor-text"
                        >
                            {option?.labelComponent ?? option?.label}
                        </LemonSnack>
                    </Tooltip>
                )
            })}
        </>
    )
}
