import './LemonInputSelect.scss'

import { DndContext, DragEndEvent, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, arrayMove, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import Fuse from 'fuse.js'
import { CSSProperties, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { List } from 'react-window'

import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { range } from 'lib/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton, LemonButtonPropsBase, SideAction } from '../LemonButton'
import { LemonDropdown } from '../LemonDropdown'
import { LemonInput, LemonInputProps } from '../LemonInput'
import { PopoverReferenceContext } from '../Popover'
import { TooltipTitle } from '../Tooltip/Tooltip'

const NON_ESCAPED_COMMA_REGEX = /(?<!\\),/

// This matches LemonButton's height when its size small
const VIRTUALIZED_SELECT_OPTION_HEIGHT = 33

const VIRTUALIZED_MAX_DROPDOWN_HEIGHT = 420

interface VirtualizedOptionRowProps<T = string> {
    visibleOptions: LemonInputSelectOption<T>[]
    selectedIndex: number
    stringKeys: string[]
    wasLimitReached: boolean
    limit?: number
    _onActionItem: (key: string, e?: MouseEvent) => void
    setSelectedIndex: (index: number) => void
    allowCustomValues?: boolean
    disableEditing?: boolean
    setInputValue: (value: string) => void
    inputRef: React.RefObject<HTMLInputElement | null>
    _onFocus: () => void
    getInputLabel: (option: LemonInputSelectOption<T>) => React.ReactNode
    getOptionIcon: (option: LemonInputSelectOption<T>, isSelected: boolean) => JSX.Element | null | undefined
}

function VirtualizedOptionRow<T = string>({
    index,
    style,
    visibleOptions,
    selectedIndex,
    stringKeys,
    wasLimitReached,
    limit,
    _onActionItem,
    setSelectedIndex,
    allowCustomValues,
    disableEditing,
    setInputValue,
    inputRef,
    _onFocus,
    getInputLabel,
    getOptionIcon,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & VirtualizedOptionRowProps<T>): JSX.Element {
    const option = visibleOptions[index]
    const isFocused = index === selectedIndex
    const isSelected = stringKeys.includes(option.key)
    const isDisabled = wasLimitReached && !isSelected
    return (
        <LemonButton
            style={style}
            key={option.key}
            type="tertiary"
            size="small"
            fullWidth
            active={isFocused}
            onClick={(e) => !isDisabled && _onActionItem(option.key, e)}
            onMouseEnter={() => setSelectedIndex(index)}
            disabledReason={isDisabled ? `Limit of ${limit} options reached` : undefined}
            tooltip={option.tooltip}
            icon={getOptionIcon(option, isSelected)}
            sideAction={
                !option.__isInput && allowCustomValues && !disableEditing
                    ? {
                          icon: <IconPencil className={!isFocused ? 'invisible' : undefined} />,
                          tooltip: (
                              <>
                                  Edit this value
                                  <KeyboardShortcut option enter />
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
                {!option.__isInput && !option.__isCustomValue
                    ? (option.labelComponent ?? option.label)
                    : getInputLabel(option)}
            </span>
        </LemonButton>
    )
}

export interface LemonInputSelectOption<T = string> {
    key: string
    label: string
    labelComponent?: React.ReactNode
    tooltip?: TooltipTitle
    /** @internal */
    __isInput?: boolean
    /** @internal - marks custom values (user-created, not in original options) */
    __isCustomValue?: boolean
    /** Original typed value - when provided, this will be used in onChange callbacks */
    value?: T
}

export type LemonInputSelectAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export type LemonInputSelectProps<T = string> = Pick<
    // NOTE: We explicitly pick rather than omit to ensure these components aren't used incorrectly
    LemonInputProps,
    'autoFocus' | 'autoWidth' | 'fullWidth'
> & {
    options?: LemonInputSelectOption<T>[]
    value?: T[] | null
    limit?: number // Limit the number of options to show
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    title?: string // Title shown at the top of the list. Looks the same as section titles in LemonMenu.
    disableFiltering?: boolean
    disablePrompting?: boolean
    mode: 'multiple' | 'single'
    allowCustomValues?: boolean
    /** Disable editing functionality (hides edit icons) while still allowing custom values */
    disableEditing?: boolean
    /** Format the label for custom values. Supports text (e.g. appending " (new entry)") and html. */
    formatCreateLabel?: (input: string) => React.ReactNode
    /** Transform input value as user types, e.g. normalization like replacing spaces with dashes. */
    inputTransform?: (input: string) => string
    emptyStateComponent?: React.ReactNode
    onChange?: (newValue: T[]) => void
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
    /** Disable comma splitting for properties that contain commas in their values (e.g., user agent strings) */
    disableCommaSplitting?: boolean
    action?: LemonInputSelectAction
    virtualized?: boolean
    /** Enable drag-and-drop reordering of values */
    sortable?: boolean
}

export function LemonInputSelect<T = string>({
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
    formatCreateLabel,
    inputTransform,
    disablePrompting = false,
    allowCustomValues = false,
    disableEditing = false,
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
    disableCommaSplitting = false,
    action,
    virtualized = false,
    sortable = false,
}: LemonInputSelectProps<T>): JSX.Element {
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

    // Create lookup maps for O(1) performance - only recompute when options change
    const optionMaps = useMemo(() => {
        const valueToOption = new Map<T, LemonInputSelectOption<T>>()
        const keyToOption = new Map<string, LemonInputSelectOption<T>>()
        const keySet = new Set<string>()

        for (const option of options) {
            if (option.value !== undefined) {
                valueToOption.set(option.value, option)
            }
            keyToOption.set(option.key, option)
            keySet.add(option.key)
        }

        return { valueToOption, keyToOption, keySet }
    }, [options])

    // Simple helper functions using O(1) lookups
    const getStringKey = useCallback(
        (value: T): string => {
            // First try to find an option with this exact value
            const option = optionMaps.valueToOption.get(value)
            if (option) {
                return option.key
            }

            // For backwards compatibility: if value is string and exists as key, use it
            if (typeof value === 'string' && optionMaps.keyToOption.has(value)) {
                const keyOption = optionMaps.keyToOption.get(value)
                if (keyOption?.value === undefined) {
                    return value as string
                }
            }

            // Fallback: convert to string
            return String(value)
        },
        [optionMaps]
    )

    const getDisplayLabel = useCallback(
        (value: T): string => {
            const option = optionMaps.valueToOption.get(value)
            return option?.label ?? String(value)
        },
        [optionMaps]
    )

    const getTypedValue = useCallback(
        (key: string): T => {
            const option = optionMaps.keyToOption.get(key)
            if (option?.value !== undefined) {
                return option.value
            }
            // Backwards compatibility: if no value provided, use key as value
            return key as T
        },
        [optionMaps]
    )

    const fuseRef = useRef<Fuse<LemonInputSelectOption<T>>>(
        new Fuse(options, {
            keys: ['label', 'key'],
        })
    )

    const separateOnComma = allowCustomValues && mode === 'multiple' && !disableCommaSplitting

    // We stringify the objects to prevent wasteful recalculations (esp. Fuse). Note: labelComponent is not serializable
    const optionsKey = JSON.stringify(options, (key, value) => (key === 'labelComponent' ? value?.name : value))
    const stringKeys = values.map(getStringKey)
    const valuesKey = JSON.stringify(stringKeys)
    const allOptionsMap: Map<string, LemonInputSelectOption<T>> = useMemo(() => {
        // Custom values are values that are not in the options list - O(n) instead of O(n×m)
        const customValues = stringKeys.filter((key) => !optionMaps.keySet.has(key))
        // Custom values are shown as options before other options (Map guarantees preserves insertion order)
        const allOptionsMap = new Map<string, LemonInputSelectOption<T>>()
        for (const customValue of customValues) {
            // Mark custom values with __isCustomValue flag so they use formatCreateLabel in the dropdown not only when typing
            // but also when re-opening the dropdown after typing
            allOptionsMap.set(customValue, { key: customValue, label: customValue, __isCustomValue: true })
        }
        for (const option of options) {
            allOptionsMap.set(option.key, option)
        }
        // The below is a side effect (boo!) - but it's fine, since it's idempotent
        fuseRef.current.setCollection(Array.from(allOptionsMap.values()))
        return allOptionsMap
    }, [optionsKey, valuesKey, optionMaps, options, stringKeys])

    const visibleOptions = useMemo(() => {
        const ret: LemonInputSelectOption<T>[] = []
        // Show the input value if custom values are allowed and it's not in the list
        if (inputValue && !stringKeys.includes(inputValue)) {
            if (allowCustomValues && !optionMaps.keySet.has(inputValue)) {
                const unescapedInputValue = inputValue.replaceAll('\\,', ',') // Transform escaped commas to plain commas
                ret.push({ key: unescapedInputValue, label: unescapedInputValue, __isInput: true })
            }
        } else if (mode === 'single' && values.length > 0) {
            // In single-select mode, show the selected value at the top
            const firstKey = getStringKey(values[0])
            ret.push(allOptionsMap.get(firstKey) ?? { key: firstKey, label: getDisplayLabel(values[0]) })
        }

        let relevantOptions: LemonInputSelectOption<T>[]
        if (!disableFiltering && inputValue) {
            // If filtering is enabled and there's input, perform fuzzy search…
            const results = fuseRef.current.search(inputValue)
            relevantOptions = results.map((result) => result.item)
        } else {
            // …otherwise show all options
            relevantOptions = Array.from(allOptionsMap.values())
        }
        for (const option of relevantOptions) {
            if (option.key === inputValue && option.__isInput) {
                // We don't want to show the input-based option again. The check for __isInput covers the case the user types something that is already an option, but we want to keep the original option
                continue
            }
            if (mode === 'single' && values.length > 0 && option.key === getStringKey(values[0])) {
                // In single-select mode, we've already added the selected value to the top earlier
                continue
            }
            ret.push(option)
            if (ret.length >= 100 && !virtualized) {
                // :HACKY: This is a quick fix to make the select dropdown work for large values, as it was getting slow when
                // we'd load more than ~10k entries. Ideally we'd make this a virtualized list.
                break
            }
        }

        return ret
    }, [
        allOptionsMap,
        allowCustomValues,
        inputValue,
        mode,
        stringKeys,
        getDisplayLabel,
        getStringKey,
        values,
        disableFiltering,
        values.length,
        virtualized,
        optionMaps,
    ])

    // Reset the selected index when the visible options change
    useEffect(() => {
        setSelectedIndex(0)
    }, [visibleOptions.map((option) => option.key).join(':::')])

    const setInputValue = (newValue: string): void => {
        // Apply input transformation if provided
        if (inputTransform) {
            newValue = inputTransform(newValue)
        }

        // Special case for multiple mode with custom values
        if (separateOnComma && newValue.match(NON_ESCAPED_COMMA_REGEX)) {
            const newValues = [...values]

            // We split on commas EXCEPT if they're escaped (to allow for commas in values)
            newValue.split(NON_ESCAPED_COMMA_REGEX).forEach((stringValue) => {
                const trimmedValue = stringValue.replaceAll('\\,', ',').trim() // Transform escaped commas to plain commas
                if (trimmedValue && !stringKeys.includes(trimmedValue)) {
                    // Convert string back to typed value
                    const typedValue = getTypedValue(trimmedValue)
                    newValues.push(typedValue)
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

    const _removeItem = (item: string, currentValues: T[] = values): void => {
        // Remove the item
        if (mode === 'single') {
            onChange?.([])
            return
        }
        const newValues = currentValues.slice()
        // Find the typed value that corresponds to this string key
        const typedValue = getTypedValue(item)
        const index = newValues.findIndex((val) => val === typedValue)
        if (index !== -1) {
            newValues.splice(index, 1)
        }
        onChange?.(newValues)
    }

    const _addItem = (item: string, atIndex?: number | null, currentValues: T[] = values): void => {
        setInputValue('')
        // Convert string key back to typed value
        const actualTypedValue = getTypedValue(item)
        if (mode === 'single') {
            onChange?.([actualTypedValue])
            return
        }
        const newValues = currentValues.slice()
        if (!newValues.includes(actualTypedValue)) {
            if (atIndex != undefined) {
                newValues.splice(atIndex, 0, actualTypedValue)
            } else {
                newValues.push(actualTypedValue)
            }
        }
        onChange?.(newValues)
    }

    const _onActionItem = (
        item: string,
        popoverOptionClickEvent?: MouseEvent | null,
        shouldInitiateEdit?: boolean
    ): void => {
        if (shouldInitiateEdit && allowCustomValues) {
            // In this case we want to remove it if added and set input to it
            const typedValue = getTypedValue(item)
            let indexOfValue = values.indexOf(typedValue)
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
            // Remove focus from input after selecting an option, since in single mode that feels better UX-wise
            inputRef.current?.blur()
        }

        if (stringKeys.includes(item)) {
            // In single mode, clicking an already-selected value should keep it selected, not toggle it off
            // (clicking an already selected item to toggle it off makes sense for multiple-select, not for single-select)
            if (mode !== 'single') {
                _removeItem(item)
            }
        } else {
            _addItem(item, itemBeingEditedIndex)
        }
    }

    const _onBlur = (): void => {
        const hasSelectedAutofilledValue = selectedIndex > 0
        const hasCustomValue =
            !hasSelectedAutofilledValue && allowCustomValues && inputValue.trim() && !stringKeys.includes(inputValue)
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
        // In single mode, when focusing with a selected value, enter edit mode right away
        if (mode === 'single' && values.length > 0 && !inputValue) {
            setInputValue(getStringKey(values[0]))
        }
        onFocus?.()
        setShowPopover(true)
        popoverFocusRef.current = true
    }

    const _onClick = (): void => {
        // Open dropdown on click even if input already has focus
        // This handles the case where user clicked outside to close dropdown but input stayed focused
        if (!showPopover) {
            setShowPopover(true)
            popoverFocusRef.current = true
        }
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
            } else if (mode === 'single') {
                // In single mode, "selected all + backspace" should clear the selection
                const input = e.currentTarget
                if (input.selectionStart === 0 && input.selectionEnd === input.value.length) {
                    e.preventDefault()
                    setInputValue('')
                    onChange?.([])
                }
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setSelectedIndex(Math.min(selectedIndex + 1, visibleOptions.length - 1))
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setSelectedIndex(Math.max(selectedIndex - 1, 0))
        }
    }

    const handleDragEnd = useCallback(
        (event: DragEndEvent): void => {
            const { active, over } = event

            if (over && active.id !== over.id) {
                const oldIndex = values.findIndex((val) => getStringKey(val) === active.id)
                const newIndex = values.findIndex((val) => getStringKey(val) === over.id)

                if (oldIndex !== -1 && newIndex !== -1) {
                    const newValues = arrayMove(values, oldIndex, newIndex)
                    onChange?.(newValues)
                }
            }
        },
        [values, getStringKey, onChange]
    )

    const valuesPrefix = useMemo(() => {
        // For single mode with a selected value and no active input, show the value as prefix since
        // showing the entered value as placeholder was unintuitive
        if (mode === 'single' && values.length > 0 && !inputValue) {
            return (
                <PopoverReferenceContext.Provider value={null}>
                    <span className="font-medium truncate">
                        {allOptionsMap.get(getStringKey(values[0]))?.label ?? getDisplayLabel(values[0])}
                    </span>
                </PopoverReferenceContext.Provider>
            )
        }

        if (mode !== 'multiple' || values.length === 0 || displayMode !== 'snacks') {
            return null
        }

        const preInputValues = itemBeingEditedIndex !== null ? values.slice(0, itemBeingEditedIndex) : values

        // TRICKY: We don't want the popover to affect the snack buttons
        return (
            <PopoverReferenceContext.Provider value={null}>
                <ValueSnacks
                    values={preInputValues.map(getStringKey)}
                    options={options}
                    onClose={(value) => _onActionItem(value, null)}
                    onInitiateEdit={
                        allowCustomValues && !disableEditing ? (value) => _onActionItem(value, null, true) : null
                    }
                    sortable={sortable}
                    onDragEnd={handleDragEnd}
                />
            </PopoverReferenceContext.Provider>
        )
    }, [
        mode,
        values,
        values.length,
        inputValue,
        allOptionsMap,
        getStringKey,
        getDisplayLabel,
        displayMode,
        itemBeingEditedIndex,
        options,
        allowCustomValues,
        disableEditing,
        _onActionItem,
        sortable,
        handleDragEnd,
    ])

    const valuesAndClearButtonSuffix = useMemo(() => {
        // In single-select mode with custom values, show a clear button when a value is selected and not in edit mode
        const isClearButtonVisible =
            mode !== 'multiple' && allowCustomValues && !disableEditing && values.length && !inputValue

        const postInputValues =
            displayMode === 'snacks' && itemBeingEditedIndex !== null ? values.slice(itemBeingEditedIndex) : []

        if (!isClearButtonVisible && postInputValues.length === 0) {
            return null
        }

        return (
            <PopoverReferenceContext.Provider value={null}>
                <ValueSnacks
                    values={postInputValues.map(getStringKey)}
                    options={options}
                    onClose={(value) => _onActionItem(value, null)}
                    onInitiateEdit={
                        allowCustomValues && !disableEditing ? (value) => _onActionItem(value, null, true) : null
                    }
                    sortable={sortable}
                    onDragEnd={handleDragEnd}
                />
                {isClearButtonVisible && (
                    <div
                        className={clsx(
                            'grow flex flex-col items-end LemonInputSelect__edit-button-wrapper',
                            size && `LemonInputSelect__edit-button-wrapper--${size}`
                        )}
                    >
                        <LemonButton
                            icon={<IconX />}
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                setInputValue('')
                                onChange?.([])
                            }}
                            tooltip="Clear selection"
                            noPadding
                        />
                    </div>
                )}
            </PopoverReferenceContext.Provider>
        )
    }, [
        mode,
        values,
        allowCustomValues,
        disableEditing,
        itemBeingEditedIndex,
        inputValue,
        getStringKey,
        _onActionItem,
        displayMode,
        _onFocus,
        options,
        setInputValue,
        sortable,
        handleDragEnd,
        size,
        onChange,
    ])

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

    const virtualizedListHeight = useMemo(() => {
        if (visibleOptions.length <= 1) {
            return VIRTUALIZED_SELECT_OPTION_HEIGHT
        }
        const height = visibleOptions.length * VIRTUALIZED_SELECT_OPTION_HEIGHT

        if (height > VIRTUALIZED_MAX_DROPDOWN_HEIGHT) {
            return VIRTUALIZED_MAX_DROPDOWN_HEIGHT
        }
        return height
    }, [visibleOptions])

    const wasLimitReached = values.length >= limit

    const getInputLabel = (option: LemonInputSelectOption<T>): React.ReactNode => {
        if (formatCreateLabel) {
            return formatCreateLabel(option.key)
        }
        return mode === 'multiple' ? `Add "${option.key}"` : option.key
    }

    const getOptionIcon = (
        option: LemonInputSelectOption<T>,
        isSelected: boolean
    ): React.ReactElement | null | undefined => {
        if (option.__isInput) {
            return undefined
        }

        if (isSelected) {
            return mode === 'multiple' ? (
                // No pointer events, since it's only for visual feedback
                <LemonCheckbox checked={true} className="pointer-events-none" />
            ) : (
                <IconCheck />
            )
        }

        if (mode === 'multiple') {
            return <LemonCheckbox checked={false} className="pointer-events-none" />
        }

        return undefined
    }

    return (
        <LemonDropdown
            matchWidth
            closeOnClickInside={false}
            actionable
            visible={showPopover}
            onClickOutside={() => {
                popoverFocusRef.current = false
                setShowPopover(false)
                // It seems more intuitive to lose focus of drop down entirely when clicking outside of the field.
                // If this behavior at some point is not desired for multiple mode anymore, it should be kept for single mode.
                inputRef.current?.blur()
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
                                    onClick={() => {
                                        const allKeys = Array.from(allOptionsMap.keys())
                                        const allTypedValues = allKeys.map(getTypedValue)
                                        onChange?.(allTypedValues)
                                    }}
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
                        virtualized ? (
                            <div>
                                <AutoSizer
                                    renderProp={({ width }) =>
                                        width ? (
                                            <List<VirtualizedOptionRowProps<T>>
                                                style={{ width, height: virtualizedListHeight }}
                                                rowCount={visibleOptions.length}
                                                overscanCount={100}
                                                rowHeight={VIRTUALIZED_SELECT_OPTION_HEIGHT}
                                                rowComponent={VirtualizedOptionRow}
                                                rowProps={{
                                                    visibleOptions,
                                                    selectedIndex,
                                                    stringKeys,
                                                    wasLimitReached,
                                                    limit,
                                                    _onActionItem,
                                                    setSelectedIndex,
                                                    allowCustomValues,
                                                    disableEditing,
                                                    setInputValue,
                                                    inputRef,
                                                    _onFocus,
                                                    getInputLabel,
                                                    getOptionIcon,
                                                }}
                                            />
                                        ) : null
                                    }
                                />
                            </div>
                        ) : (
                            visibleOptions.map((option, index) => {
                                const isFocused = index === selectedIndex
                                const isSelected = stringKeys.includes(option.key)
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
                                        icon={getOptionIcon(option, isSelected)}
                                        sideAction={
                                            !option.__isInput && allowCustomValues && !disableEditing
                                                ? {
                                                      // To reduce visual clutter we only show the icon on focus or hover,
                                                      // but we do want it present to make sure the layout is stable
                                                      icon: (
                                                          <IconPencil
                                                              className={!isFocused ? 'invisible' : undefined}
                                                          />
                                                      ),
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
                                            {
                                                !option.__isInput && !option.__isCustomValue
                                                    ? (option.labelComponent ?? option.label) // Regular option
                                                    : getInputLabel(option) // Input-based option
                                            }
                                        </span>
                                    </LemonButton>
                                )
                            })
                        )
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
                            ? undefined // When value is selected in single mode, no placeholder (value shown but rendered as prefix)
                            : allowCustomValues
                              ? 'Add value'
                              : disablePrompting
                                ? undefined
                                : 'Pick value'
                }
                autoWidth={fullWidth ? false : autoWidth}
                fullWidth={fullWidth}
                prefix={valuesPrefix}
                suffix={
                    <>
                        {countPlaceholder}
                        {valuesAndClearButtonSuffix}
                    </>
                }
                onFocus={_onFocus}
                onBlur={_onBlur}
                value={inputValue}
                onChange={setInputValue}
                onClick={_onClick}
                onKeyDown={_onKeyDown}
                disabled={disabled}
                autoFocus={autoFocus}
                transparentBackground={transparentBackground}
                className={clsx(
                    '!h-auto leading-7 max-w-full w-full', // leading-7 means line height aligned with LemonSnack height
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

function DraggableValueSnack<T = string>({
    value,
    option,
    onClose,
    onInitiateEdit,
}: {
    value: string
    option: LemonInputSelectOption<T>
    onClose: (value: string) => void
    onInitiateEdit: ((value: string) => void) | null
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: value,
    })

    const style = {
        transform: CSS.Translate.toString(transform),
        transition,
        zIndex: isDragging ? 1 : undefined,
        opacity: isDragging ? 0.5 : undefined,
    }

    return (
        <Tooltip
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
            <span
                ref={setNodeRef}
                // eslint-disable-next-line react/forbid-dom-props
                style={style}
                {...attributes}
                className="inline-flex text-primary-alt max-w-full overflow-hidden break-all items-center py-1 leading-5 bg-accent-highlight-secondary rounded"
            >
                <span
                    className="shrink-0 flex items-center pl-1 pr-0.5 cursor-grab active:cursor-grabbing"
                    {...listeners}
                >
                    <SortableDragIcon className="text-muted-alt w-3.5" />
                </span>
                <span
                    className="overflow-hidden text-ellipsis px-1 cursor-text"
                    title={option?.label}
                    onClick={onInitiateEdit ? () => onInitiateEdit(value) : undefined}
                >
                    {option?.labelComponent ?? option?.label}
                </span>
                <span className="shrink-0 mx-1">
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconX />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onClose(value)
                        }}
                    />
                </span>
            </span>
        </Tooltip>
    )
}

function ValueSnacks<T = string>({
    values,
    options,
    onClose,
    onInitiateEdit,
    sortable = false,
    onDragEnd,
}: {
    values: string[]
    options: LemonInputSelectOption<T>[]
    onClose: (value: string) => void
    onInitiateEdit: ((value: string) => void) | null
    sortable?: boolean
    onDragEnd?: (event: DragEndEvent) => void
}): JSX.Element {
    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: {
                distance: 8,
            },
        })
    )

    const content = values.map((value) => {
        const option: LemonInputSelectOption<T> = options.find((option) => option.key === value) ?? {
            key: value,
            label: value,
            labelComponent: null,
        }

        if (sortable) {
            return (
                <DraggableValueSnack
                    key={value}
                    value={value}
                    option={option}
                    onClose={onClose}
                    onInitiateEdit={onInitiateEdit}
                />
            )
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
    })

    if (sortable && onDragEnd) {
        return (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={values} strategy={rectSortingStrategy}>
                    {content}
                </SortableContext>
            </DndContext>
        )
    }

    return <>{content}</>
}
