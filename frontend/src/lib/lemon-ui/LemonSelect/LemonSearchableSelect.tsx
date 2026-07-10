import clsx from 'clsx'
import { useMemo, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { createFuse } from 'lib/utils/fuseSearch'

import {
    LemonSelect,
    LemonSelectOption,
    LemonSelectOptions,
    LemonSelectPropsBase,
    LemonSelectPropsClearable,
    LemonSelectPropsNonClearable,
    LemonSelectSection,
    isLemonSelectSection,
} from './LemonSelect'

export interface LemonSearchableSelectPropsBase<T> extends LemonSelectPropsBase<T> {
    searchPlaceholder?: string
    searchKeys?: string[]
    /** `data-attr` for the search input, so its usage can be tracked per call site. */
    searchInputDataAttr?: string
    /** Message shown when a search term matches no options. */
    noResultsMessage?: string
}

export interface LemonSearchableSelectPropsClearable<T>
    extends LemonSearchableSelectPropsBase<T>, LemonSelectPropsClearable<T> {}

export interface LemonSearchableSelectPropsNonClearable<T>
    extends LemonSearchableSelectPropsBase<T>, LemonSelectPropsNonClearable<T> {}

export type LemonSearchableSelectProps<T> =
    | LemonSearchableSelectPropsClearable<T>
    | LemonSearchableSelectPropsNonClearable<T>

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

export function LemonSearchableSelect<T extends string | number | boolean | null>({
    searchPlaceholder,
    searchKeys = ['label'],
    searchInputDataAttr = 'lemon-searchable-select-search',
    noResultsMessage = 'No results',
    onChange,
    onSelect,
    ...selectProps
}: LemonSearchableSelectProps<T>): JSX.Element {
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
        <LemonSelect
            {...selectProps}
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
