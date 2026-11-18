import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSearchableSelect, LemonSelect, LemonSelectOptionLeaf, Spinner } from '@posthog/lemon-ui'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { anyOptionLabel, discoveredSelectOptions } from './discoveredSelectOptions'
import { withSelectedOption } from './quickFilterOptions'
import { discoveredValuesMessage, quickFilterValuesLogic } from './quickFilterValuesLogic'

interface QuickFilterSelectorProps {
    filter: Pick<QuickFilter, 'name' | 'property_name' | 'type' | 'options'>
    context: QuickFilterContext
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

type SelectValue = string | null

function selectOptions(filterName: string, options: QuickFilterOption[]): LemonSelectOptionLeaf<SelectValue>[] {
    return [
        { value: null, label: anyOptionLabel(filterName) },
        ...options.map((option) => ({ value: option.id, label: option.label })),
    ]
}

function selectedValue(options: QuickFilterOption[], selectedOptionId: string | null): SelectValue {
    return selectedOptionId && options.some((option) => option.id === selectedOptionId) ? selectedOptionId : null
}

function findOption(options: QuickFilterOption[], optionId: SelectValue): QuickFilterOption | null {
    return optionId === null ? null : (options.find((option) => option.id === optionId) ?? null)
}

export function QuickFilterSelector(props: QuickFilterSelectorProps): JSX.Element {
    return props.filter.type === 'auto-discovery' ? (
        <DiscoveredValuesSelector {...props} />
    ) : (
        <ManualOptionsSelector {...props} />
    )
}

function ManualOptionsSelector({ filter, selectedOptionId, onChange }: QuickFilterSelectorProps): JSX.Element {
    const options = useMemo(() => selectOptions(filter.name, filter.options), [filter.name, filter.options])

    return (
        <LemonSelect
            value={selectedValue(filter.options, selectedOptionId)}
            onChange={(optionId) => onChange(findOption(filter.options, optionId))}
            options={options}
            size="small"
            placeholder={filter.name || 'Filter name'}
            dropdownMatchSelectWidth={false}
            truncateText={{ maxWidthClass: 'max-w-60' }}
        />
    )
}

function DiscoveredValuesSelector({
    filter,
    context,
    selectedOptionId,
    onChange,
}: QuickFilterSelectorProps): JSX.Element {
    const valuesLogic = quickFilterValuesLogic({ context, propertyName: filter.property_name })
    const { discoveredOptions, discoveredValuesStatus, search } = useValues(valuesLogic)
    const { setSearch } = useActions(valuesLogic)

    const options = useMemo(
        () => withSelectedOption(discoveredOptions, selectedOptionId),
        [discoveredOptions, selectedOptionId]
    )
    const message = discoveredValuesMessage(discoveredValuesStatus, search, discoveredOptions.length)
    const sections = useMemo(
        () => [
            {
                options: discoveredSelectOptions(filter.name, discoveredOptions, selectedOptionId, search),
                footer:
                    discoveredValuesStatus === 'loading' ? (
                        <span className="flex items-center gap-1">
                            <Spinner textColored />
                            {message}
                        </span>
                    ) : (
                        (message ?? undefined)
                    ),
            },
        ],
        [filter.name, discoveredOptions, selectedOptionId, search, discoveredValuesStatus, message]
    )

    return (
        <LemonSearchableSelect
            value={selectedValue(options, selectedOptionId)}
            className={selectedValue(options, selectedOptionId) ? 'ph-no-capture' : undefined}
            onChange={(optionId) => onChange(findOption(options, optionId))}
            options={sections}
            searchPlaceholder="Search values"
            searchInputDataAttr="quick-filter-values-search"
            onSearchChange={setSearch}
            filterOptionsLocally={false}
            size="small"
            placeholder={filter.name || 'Filter name'}
            dropdownMatchSelectWidth={false}
            truncateText={{ maxWidthClass: 'max-w-60' }}
            menu={{ onVisibilityChange: (visible) => visible && setSearch('') }}
        />
    )
}
