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

function filterOptions<T>(options: LemonSelectOptions<T>, searchTerm: string): LemonSelectOptions<T> {
    if (!searchTerm) {
        return options
    }

    const searchLower = searchTerm.toLowerCase()

    const filterOption = (
        option: LemonSelectOption<T> | LemonSelectSection<T>
    ): LemonSelectOption<T> | LemonSelectSection<T> | null => {
        if (isLemonSelectSection(option)) {
            const filteredOptions = option.options.map(filterOption).filter(Boolean) as LemonSelectOption<T>[]
            return filteredOptions.length > 0 ? { ...option, options: filteredOptions } : null
        } else if ('options' in option) {
            // LemonSelectOptionNode
            const filteredOptions = option.options.map(filterOption).filter(Boolean) as LemonSelectOption<T>[]
            return filteredOptions.length > 0 ? { ...option, options: filteredOptions } : null
        }
        // Leaf option
        const label = option.label || String(option.value)
        return String(label).toLowerCase().includes(searchLower) ? option : null
    }

    return options.map(filterOption).filter(Boolean) as LemonSelectOptions<T>
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
        onChange?.(newValue)
        setSearchTerm('')
    }

    return <LemonSelect {...selectProps} options={optionsWithSearch} onChange={handleChange} />
}
