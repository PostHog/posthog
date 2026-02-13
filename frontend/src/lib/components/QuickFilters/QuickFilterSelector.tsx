import { useEffect, useMemo } from 'react'

import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyFilterType, PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

import { isAutoDiscoveryQuickFilter } from './utils'

interface QuickFilterSelectorProps {
    filter: QuickFilter
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function QuickFilterSelector({ filter, selectedOptionId, onChange }: QuickFilterSelectorProps): JSX.Element {
    if (isAutoDiscoveryQuickFilter(filter)) {
        return (
            <AutoDiscoveryQuickFilterSelector
                filter={filter}
                selectedOptionId={selectedOptionId}
                onChange={onChange}
            />
        )
    }

    const options = filter.options as QuickFilterOption[]
    return (
        <ManualQuickFilterSelector
            label={filter.name}
            options={options}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
        />
    )
}

function ManualQuickFilterSelector({
    label,
    options,
    selectedOptionId,
    onChange,
}: {
    label: string
    options: QuickFilterOption[]
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}): JSX.Element {
    const allOptions = useMemo(
        () => [
            { value: null, label: `Any ${label.toLowerCase()}` },
            ...options.map((opt) => ({
                value: opt.id,
                label: opt.label,
            })),
        ],
        [options, label]
    )

    const displayValue = useMemo(() => {
        if (selectedOptionId === null) {
            return null
        }
        return options.some((opt) => opt.id === selectedOptionId) ? selectedOptionId : null
    }, [selectedOptionId, options])

    return (
        <LemonSelect
            value={displayValue}
            onChange={(selectedId) => {
                if (selectedId === null) {
                    onChange(null)
                } else {
                    const selected = options.find((opt) => opt.id === selectedId)
                    onChange(selected || null)
                }
            }}
            options={allOptions}
            size="small"
            placeholder={label}
            dropdownMatchSelectWidth={false}
        />
    )
}

function AutoDiscoveryQuickFilterSelector({
    filter,
    selectedOptionId,
    onChange,
}: {
    filter: QuickFilter & { options: { value_pattern: string; operator: PropertyOperator } }
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}): JSX.Element {
    const { options: propertyOptions } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const config = filter.options

    useEffect(() => {
        loadPropertyValues({
            endpoint: undefined,
            type: propertyFilterTypeToPropertyDefinitionType(PropertyFilterType.Event),
            newInput: '',
            propertyKey: filter.property_name,
            eventNames: [],
            properties: [],
        })
    }, [filter.property_name, loadPropertyValues])

    const propData = propertyOptions[filter.property_name]
    const isLoading = propData?.status === 'loading'

    const dynamicOptions: QuickFilterOption[] = useMemo(() => {
        const values = propData?.values || []
        let filtered = values
        if (config.value_pattern) {
            try {
                const regex = new RegExp(config.value_pattern)
                filtered = values.filter((pv) => regex.test(String(pv.name ?? '')))
            } catch {
                filtered = values
            }
        }
        return filtered.map((pv) => ({
            id: String(pv.name ?? ''),
            value: String(pv.name ?? ''),
            label: String(pv.name ?? ''),
            operator: config.operator || PropertyOperator.Exact,
        }))
    }, [propData?.values, config.value_pattern, config.operator])

    const allOptions = useMemo(
        () => [
            { value: null, label: `Any ${filter.name.toLowerCase()}` },
            ...dynamicOptions.map((opt) => ({
                value: opt.id,
                label: opt.label,
            })),
        ],
        [dynamicOptions, filter.name]
    )

    const displayValue = useMemo(() => {
        if (selectedOptionId === null) {
            return null
        }
        return dynamicOptions.some((opt) => opt.id === selectedOptionId) ? selectedOptionId : null
    }, [selectedOptionId, dynamicOptions])

    return (
        <LemonSelect
            value={displayValue}
            onChange={(selectedId) => {
                if (selectedId === null) {
                    onChange(null)
                } else {
                    const selected = dynamicOptions.find((opt) => opt.id === selectedId)
                    onChange(selected || null)
                }
            }}
            options={allOptions}
            size="small"
            placeholder={filter.name}
            dropdownMatchSelectWidth={false}
            loading={isLoading}
        />
    )
}
