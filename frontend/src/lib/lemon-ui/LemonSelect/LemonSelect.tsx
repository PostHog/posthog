import clsx from 'clsx'
import React, { useMemo, useState } from 'react'

import { IconX } from '@posthog/icons'

import { LemonDropdownProps } from 'lib/lemon-ui/LemonDropdown'
import { createFuse } from 'lib/utils/fuseSearch'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonInput } from '../LemonInput'
import {
    LemonMenu,
    LemonMenuItem,
    LemonMenuItemBase,
    LemonMenuItemLeaf,
    LemonMenuItemNode,
    LemonMenuProps,
    LemonMenuSection,
    isLemonMenuSection,
} from '../LemonMenu/LemonMenu'
import { PopoverProps } from '../Popover'
import { TooltipProps } from '../Tooltip'

// Select options are basically menu items that handle onClick and active state internally
interface LemonSelectOptionBase extends Omit<LemonMenuItemBase, 'active' | 'status'> {
    /** Support this option if it already is selected, but otherwise don't allow selecting it by hiding it. */
    hidden?: boolean
}

type LemonSelectCustomControl<T> = ({ onSelect }: { onSelect: (newValue: T) => void }) => JSX.Element
export interface LemonSelectOptionLeaf<T> extends LemonSelectOptionBase {
    value: T
    /**
     * Label for display inside the dropdown menu.
     *
     * If you really need something more advanced than a button, this also allows providing a custom control component,
     * which takes an `onSelect` prop. Can be for example a textarea with an "Apply value" button. Use this sparingly!
     */
    labelInMenu?: string | JSX.Element | LemonSelectCustomControl<T>
}

export interface LemonSelectOptionNode<T> extends LemonSelectOptionBase {
    options: LemonSelectOptions<T>
}

export type LemonSelectOption<T> = LemonSelectOptionLeaf<T> | LemonSelectOptionNode<T>

export interface LemonSelectSection<T> {
    title?: string | React.ReactNode
    options: LemonSelectOption<T>[]
    footer?: string | React.ReactNode
}

export type LemonSelectOptions<T> = LemonSelectSection<T>[] | LemonSelectOption<T>[]

export interface LemonSelectPropsBase<T> extends Pick<
    LemonButtonProps,
    | 'id'
    | 'className'
    | 'loading'
    | 'fullWidth'
    | 'disabled'
    | 'disabledReason'
    | 'data-attr'
    | 'aria-label'
    | 'onClick'
    | 'tabIndex'
    | 'type'
    | 'status'
    | 'active'
    | 'tooltip'
    | 'icon'
> {
    options: LemonSelectOptions<T>
    /** Callback fired when a value is selected, even if it already is set. */
    onSelect?: (newValue: T) => void
    optionTooltipPlacement?: TooltipProps['placement']
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopoverProps['placement']
    className?: string
    placeholder?: string
    size?: LemonButtonProps['size']
    menu?: Pick<LemonMenuProps, 'className' | 'closeParentPopoverOnClickInside' | 'onVisibilityChange'>
    visible?: LemonDropdownProps['visible']
    startVisible?: LemonDropdownProps['startVisible']
    truncateText?: { maxWidthClass: string }
    /**
     * Whether to show a search input at the top of the dropdown menu.
     * Defaults to automatic: search is enabled when there are more than 15 selectable options.
     */
    searchable?: boolean
    searchPlaceholder?: string
    /** Option keys the search matches against. Defaults to `['label']`. */
    searchKeys?: string[]
    /** `data-attr` for the search input, so its usage can be tracked per call site. */
    searchInputDataAttr?: string
    /** Message shown when a search term matches no options. */
    noResultsMessage?: string
}

export interface LemonSelectPropsClearable<T> extends LemonSelectPropsBase<T> {
    allowClear: true
    /** Should only be undefined in form fields. */
    value?: T | null
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: T | null) => void
    renderButtonContent?: (leaf: LemonSelectOptionLeaf<T | null> | undefined) => string | JSX.Element
}

export interface LemonSelectPropsNonClearable<T> extends LemonSelectPropsBase<T> {
    allowClear?: false
    /** Should only be undefined in form fields. */
    value?: T
    /** Callback fired when a value different from the one currently set is selected. */
    onChange?: (newValue: T) => void
    renderButtonContent?: (leaf: LemonSelectOptionLeaf<T | null> | undefined) => string | JSX.Element
}

export type LemonSelectProps<T> = LemonSelectPropsClearable<T> | LemonSelectPropsNonClearable<T>

/** Above this many selectable options, the dropdown gets a search input unless `searchable` is set explicitly. */
export const LEMON_SELECT_AUTO_SEARCH_THRESHOLD = 15

export function LemonSelect<T extends string | number | boolean | null>({
    searchable,
    ...props
}: LemonSelectProps<T>): JSX.Element {
    const isSearchable = useMemo(
        () => searchable ?? getSearchableLeaves(props.options).length > LEMON_SELECT_AUTO_SEARCH_THRESHOLD,
        [searchable, props.options]
    )
    // Cast to `any` because LemonSelectProps is a union (clearable vs non-clearable) and TS can't spread it as JSX props.
    return isSearchable ? <LemonSelectWithSearch {...(props as any)} /> : <LemonSelectBase {...(props as any)} />
}

function LemonSelectBase<T extends string | number | boolean | null>({
    value = null,
    onChange,
    onSelect,
    options,
    placeholder = 'Select a value',
    searchPlaceholder,
    searchKeys,
    searchInputDataAttr,
    noResultsMessage,
    optionTooltipPlacement,
    dropdownMatchSelectWidth = true,
    dropdownMaxContentWidth = false,
    dropdownPlacement,
    allowClear = false,
    className,
    menu,
    renderButtonContent,
    visible,
    startVisible,
    truncateText,
    ...buttonProps
}: LemonSelectProps<T>): JSX.Element {
    const [items, allLeafOptions] = useMemo(
        () =>
            convertSelectOptionsToMenuItems(options, value, (newValue) => {
                if (newValue !== value) {
                    onChange?.(newValue)
                }
                onSelect?.(newValue)
            }),
        [options, value, onChange, onSelect]
    )

    const activeLeaf = allLeafOptions.find((o) => o.value === value)
    const isClearButtonShown = allowClear && !!value

    return (
        <LemonMenu
            items={items}
            tooltipPlacement={optionTooltipPlacement}
            matchWidth={dropdownMatchSelectWidth}
            placement={dropdownPlacement}
            className={menu?.className}
            maxContentWidth={dropdownMaxContentWidth}
            activeItemIndex={items
                .flatMap((i) => (isLemonMenuSection(i) ? i.items.filter(Boolean) : i))
                .findIndex((i) => (i as LemonMenuItem).active)}
            closeParentPopoverOnClickInside={menu?.closeParentPopoverOnClickInside}
            onVisibilityChange={menu?.onVisibilityChange}
            visible={visible}
            startVisible={startVisible}
        >
            <LemonButton
                className={clsx(className, 'LemonSelect')}
                icon={activeLeaf?.icon}
                type="secondary"
                sideAction={
                    isClearButtonShown
                        ? {
                              icon: <IconX />,
                              divider: false,
                              onClick: () => {
                                  onChange?.(null as unknown as T)
                              },
                          }
                        : null
                }
                sideIcon={
                    !isClearButtonShown
                        ? (activeLeaf?.sideIcon as never) // This is necessary to satisfy TS that sideIcon and sideAction ARE mutually exclusive in practice
                        : undefined
                }
                tooltip={activeLeaf?.tooltip}
                {...buttonProps}
            >
                <span
                    className={
                        truncateText
                            ? `block w-full overflow-hidden text-ellipsis whitespace-nowrap ${truncateText.maxWidthClass}`
                            : 'flex flex-1'
                    }
                >
                    {renderButtonContent
                        ? renderButtonContent(activeLeaf)
                        : activeLeaf
                          ? activeLeaf.label
                          : ((value ?? placeholder) as React.ReactNode)}
                </span>
            </LemonButton>
        </LemonMenu>
    )
}

/**
 * The select can receive `options` that are either Options or Sections.
 *
 * To simplify the implementation we box the options so that the code only deals with sections
 * and also generate a single list of options since selection is separate from display structure
 * */
function convertSelectOptionsToMenuItems<T>(
    options: LemonSelectOptions<T>,
    activeValue: T | null,
    onSelect: NonNullable<LemonSelectPropsBase<T>['onSelect']>
): [(LemonMenuItem | LemonMenuSection)[], LemonSelectOptionLeaf<T>[]] {
    const leafOptionsAccumulator: LemonSelectOptionLeaf<T>[] = []
    const items = options
        .map((option) => convertToMenuSingle(option, activeValue, onSelect, leafOptionsAccumulator))
        .filter(Boolean) as (LemonMenuItem | LemonMenuSection)[]
    return [items, leafOptionsAccumulator]
}

function convertToMenuSingle<T>(
    option: LemonSelectOption<T> | LemonSelectSection<T>,
    activeValue: T | null,
    onSelect: NonNullable<LemonSelectPropsBase<T>['onSelect']>,
    acc: LemonSelectOptionLeaf<T>[]
): LemonMenuItem | LemonMenuSection | null {
    if (isLemonSelectSection(option)) {
        const { options: childOptions, ...section } = option
        const items = option.options.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)).filter(Boolean)
        if (!items.length) {
            // Add hidden options to the accumulator (by calling convertToMenuSingle), but don't show
            return null
        }
        return {
            ...section,
            items,
        } as LemonMenuSection
    } else if (isLemonSelectOptionNode(option)) {
        const { options: childOptions, ...node } = option
        const items = childOptions.map((o) => convertToMenuSingle(o, activeValue, onSelect, acc)).filter(Boolean)
        if (option.hidden) {
            // Add hidden options to the accumulator (by calling convertToMenuSingle), but don't show
            return null
        }
        return {
            ...node,
            active: doOptionsContainActiveValue(childOptions, activeValue),
            items,
            custom: doOptionsContainCustomControl(childOptions),
        } as LemonMenuItemNode
    }
    acc.push(option)
    if (option.hidden) {
        // Add hidden options to the accumulator, but don't show
        return null
    }
    const { value, label, labelInMenu, ...leaf } = option
    let CustomControl: LemonSelectCustomControl<T> | undefined
    if (typeof labelInMenu === 'function') {
        CustomControl = labelInMenu
    }
    return {
        ...leaf,
        label: CustomControl
            ? function LabelWrapped() {
                  if (!CustomControl) {
                      throw new Error('CustomControl became undefined')
                  }
                  return <CustomControl onSelect={onSelect} />
              }
            : labelInMenu || label,
        active: value === activeValue,
        onClick: () => onSelect(value),
    } as LemonMenuItemLeaf
}

export function isLemonSelectSection<T>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectSection<T> {
    return candidate && 'options' in candidate && !('label' in candidate)
}

export function isLemonSelectOptionNode<T>(
    candidate: LemonSelectSection<T> | LemonSelectOption<T>
): candidate is LemonSelectOptionNode<T> {
    return candidate && 'options' in candidate && 'label' in candidate
}

function doOptionsContainActiveValue<T>(options: LemonSelectOptions<T>, activeValue: T | null): boolean {
    for (const option of options) {
        if ('options' in option) {
            if (doOptionsContainActiveValue(option.options, activeValue)) {
                return true
            }
        } else if (option.value === activeValue) {
            return true
        }
    }
    return false
}

function doOptionsContainCustomControl<T>(options: LemonSelectOptions<T>): boolean {
    for (const option of options) {
        if ('options' in option) {
            if (doOptionsContainCustomControl(option.options)) {
                return true
            }
        } else if (typeof option.labelInMenu === 'function') {
            return true
        }
    }
    return false
}

function flattenOptions<T>(options: LemonSelectOptions<T>): LemonSelectOption<T>[] {
    const flatOptions: LemonSelectOption<T>[] = []
    const addOption = (option: LemonSelectOption<T> | LemonSelectSection<T>): void => {
        if ('options' in option) {
            option.options.forEach(addOption)
        } else {
            flatOptions.push(option)
        }
    }

    options.forEach((item) => {
        if (isLemonSelectSection(item)) {
            item.options.forEach(addOption)
        } else {
            addOption(item)
        }
    })

    return flatOptions
}

function filterStructure<T>(
    item: LemonSelectOption<T> | LemonSelectSection<T>,
    matchedOptions: Set<LemonSelectOption<T>>
): typeof item | null {
    if (isLemonSelectSection(item)) {
        const filteredOptions = item.options
            .map((option) => filterStructure(option, matchedOptions))
            .filter(Boolean) as LemonSelectOption<T>[]
        return filteredOptions.length > 0 ? { ...item, options: filteredOptions } : null
    }
    if ('options' in item) {
        const filteredOptions = item.options
            .map((option) => filterStructure(option, matchedOptions))
            .filter(Boolean) as LemonSelectOption<T>[]
        return filteredOptions.length > 0 ? { ...item, options: filteredOptions } : null
    }
    return matchedOptions.has(item) ? item : null
}

function filterOptions<T>(
    options: LemonSelectOptions<T>,
    searchTerm: string,
    searchKeys: string[] = ['label']
): LemonSelectOptions<T> {
    if (!searchTerm) {
        return options
    }

    const flatOptions = flattenOptions(options)
    const fuse = createFuse(flatOptions, { keys: searchKeys })
    const matchedOptions = new Set(fuse.search(searchTerm).map((result) => result.item))

    return options.map((item) => filterStructure(item, matchedOptions)).filter(Boolean) as LemonSelectOptions<T>
}

// A searchable option is a selectable leaf rendered as a plain menu-item button — not a custom
// control (e.g. a labelInMenu render function) and not a hidden option.
function getSearchableLeaves<T>(options: LemonSelectOptions<T>): LemonSelectOption<T>[] {
    return flattenOptions(options).filter(
        (option) => 'value' in option && typeof option.labelInMenu !== 'function' && !option.hidden
    )
}

// Rebuild the option tree with the active option carrying the standard LemonButton highlight class,
// so keyboard navigation highlights it the same way hovering does.
function highlightActiveOption<T>(
    options: LemonSelectOptions<T>,
    activeOption: LemonSelectOption<T> | null
): LemonSelectOptions<T> {
    if (!activeOption) {
        return options
    }
    const mark = (item: LemonSelectOption<T> | LemonSelectSection<T>): typeof item => {
        if ('options' in item) {
            return { ...item, options: item.options.map(mark) } as typeof item
        }
        return item === activeOption ? { ...item, className: clsx(item.className, 'LemonButton--active') } : item
    }
    return options.map(mark) as LemonSelectOptions<T>
}

const POPOVER_BOX_SELECTOR = '.Popover__box'
const MENU_ITEM_SELECTOR = 'button[role="menuitem"]'

function LemonSelectWithSearch<T extends string | number | boolean | null>({
    searchPlaceholder,
    searchKeys = ['label'],
    searchInputDataAttr = 'lemon-select-search',
    noResultsMessage = 'No results',
    onChange,
    onSelect,
    ...selectProps
}: LemonSelectProps<T>): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    // Index into `navigableOptions` of the row highlighted via arrow keys, or -1 for the search box.
    const [activeIndex, setActiveIndex] = useState(-1)

    const filteredOptions = useMemo(() => {
        return filterOptions(selectProps.options, searchTerm, searchKeys)
    }, [selectProps.options, searchTerm, searchKeys])

    const navigableOptions = useMemo(() => getSearchableLeaves(filteredOptions), [filteredOptions])
    const activeOption =
        activeIndex >= 0 && activeIndex < navigableOptions.length ? navigableOptions[activeIndex] : null

    const handleSearchChange = (newSearchTerm: string): void => {
        setSearchTerm(newSearchTerm)
        setActiveIndex(-1)
    }

    const scrollMenuItemIntoView = (fromElement: HTMLElement, index: number): void => {
        const menuItems = fromElement.closest(POPOVER_BOX_SELECTOR)?.querySelectorAll(MENU_ITEM_SELECTOR)
        menuItems?.[index]?.scrollIntoView({ block: 'nearest' })
    }

    const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'ArrowDown') {
            // Stop propagation so an enclosing form (e.g. LemonFormDialog) doesn't also act on the key.
            e.preventDefault()
            e.stopPropagation()
            const nextIndex = Math.min(activeIndex + 1, navigableOptions.length - 1)
            setActiveIndex(nextIndex)
            scrollMenuItemIntoView(e.currentTarget, nextIndex)
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            e.stopPropagation()
            const nextIndex = Math.max(activeIndex - 1, -1)
            setActiveIndex(nextIndex)
            if (nextIndex >= 0) {
                scrollMenuItemIntoView(e.currentTarget, nextIndex)
            }
        } else if (e.key === 'Enter') {
            // Keep Enter scoped to the dropdown so it never submits an enclosing form (e.g. LemonFormDialog),
            // even when no result is highlighted yet.
            e.preventDefault()
            e.stopPropagation()
            if (activeOption) {
                // Click the highlighted menu item so it goes through the same select-and-close path as a mouse click.
                const menuItems = e.currentTarget.closest(POPOVER_BOX_SELECTOR)?.querySelectorAll(MENU_ITEM_SELECTOR)
                ;(menuItems?.[activeIndex] as HTMLElement | undefined)?.click()
            }
        }
    }

    // Add search input as first menu item
    const optionsWithSearch = useMemo(() => {
        const searchMenuItem: LemonSelectOption<T> = {
            label: () => (
                <LemonInput
                    type="search"
                    placeholder={searchPlaceholder || 'Search'}
                    autoFocus
                    value={searchTerm}
                    onChange={handleSearchChange}
                    onKeyDown={handleSearchKeyDown}
                    fullWidth
                    onClick={(e) => e.stopPropagation()}
                    className="mb-1"
                    data-attr={searchInputDataAttr}
                />
            ),
            custom: true,
        } as any

        const hasNoResults = searchTerm.length > 0 && filteredOptions.length === 0
        const emptyMenuItem: LemonSelectOption<T> = {
            label: () => <div className="px-2 py-1.5 text-secondary">{noResultsMessage}</div>,
            custom: true,
        } as any

        const listOptions = hasNoResults ? [emptyMenuItem] : highlightActiveOption(filteredOptions, activeOption)
        return [searchMenuItem, ...listOptions] as LemonSelectOptions<T>
        // handleSearchKeyDown/handleSearchChange are stable enough for this memo; activeOption drives the highlight.
    }, [searchPlaceholder, searchTerm, filteredOptions, noResultsMessage, searchInputDataAttr, activeOption]) // eslint-disable-line react-hooks/exhaustive-deps

    const handleChange = (newValue: T | null): void => {
        // Cast to `any` because `onChange` is a union type (T vs T | null) and TS can't infer it here.
        onChange?.(newValue as any)
        setSearchTerm('')
        setActiveIndex(-1)
    }

    const handleOnSelect = (newValue: T | null): void => {
        // Cast to `any` because `onSelect` is a union type (T vs T | null) and TS can't infer it here.
        onSelect?.(newValue as any)
    }

    return (
        <LemonSelectBase
            // Cast to `any` because LemonSelectProps is a union (clearable vs non-clearable) and TS can't spread it as JSX props.
            {...(selectProps as any)}
            options={optionsWithSearch}
            onChange={handleChange}
            onSelect={handleOnSelect}
            menu={{
                ...selectProps.menu,
                onVisibilityChange: (visible) => {
                    selectProps.menu?.onVisibilityChange?.(visible)
                    // Clear the filter when the dropdown closes, otherwise a stale search term keeps the
                    // selected option filtered out and the trigger falls back to rendering the raw value.
                    if (!visible) {
                        setSearchTerm('')
                        setActiveIndex(-1)
                    }
                },
            }}
        />
    )
}
