import Fuse from 'fuse.js'
import { useMemo, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

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
}

export interface LemonSearchableSelectPropsClearable<T>
    extends LemonSearchableSelectPropsBase<T>,
        LemonSelectPropsClearable<T> {}

export interface LemonSearchableSelectPropsNonClearable<T>
    extends LemonSearchableSelectPropsBase<T>,
        LemonSelectPropsNonClearable<T> {}

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

function filterOptions<T>(options: LemonSelectOptions<T>, searchTerm: string): LemonSelectOptions<T> {
    if (!searchTerm) {
        return options
    }

    const flatOptions = flattenOptions(options)
    const fuse = new Fuse(flatOptions, { keys: ['label'], threshold: 0.3 })
    const matchedOptions = new Set(fuse.search(searchTerm).map((result) => result.item))

    return options.map((item) => filterStructure(item, matchedOptions)).filter(Boolean) as LemonSelectOptions<T>
}

export function LemonSearchableSelect<T extends string | number | boolean | null>({
    searchPlaceholder,
    onChange,
    onSelect,
    ...selectProps
}: LemonSearchableSelectProps<T>): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')

    const filteredOptions = useMemo(() => {
        return filterOptions(selectProps.options, searchTerm)
    }, [selectProps.options, searchTerm])

    // Add search input as first menu item
    const optionsWithSearch = useMemo(() => {
        const searchMenuItem: LemonSelectOption<T> = {
            label: () => (
                <LemonInput
                    type="search"
                    placeholder={searchPlaceholder || 'Search'}
                    autoFocus
                    value={searchTerm}
                    onChange={setSearchTerm}
                    fullWidth
                    onClick={(e) => e.stopPropagation()}
                    className="mb-1"
                />
            ),
            custom: true,
        } as any

        return [searchMenuItem, ...filteredOptions] as LemonSelectOptions<T>
    }, [searchPlaceholder, searchTerm, filteredOptions])

    const handleChange = (newValue: T | null): void => {
        // Cast to `any` because `onChange` is a union type (T vs T | null) and TS can't infer it here.
        onChange?.(newValue as any)
        setSearchTerm('')
    }

    const handleOnSelect = (newValue: T | null): void => {
        // Cast to `any` because `onSelect` is a union type (T vs T | null) and TS can't infer it here.
        onSelect?.(newValue as any)
    }

    return (
        <LemonSelect {...selectProps} options={optionsWithSearch} onChange={handleChange} onSelect={handleOnSelect} />
    )
}
