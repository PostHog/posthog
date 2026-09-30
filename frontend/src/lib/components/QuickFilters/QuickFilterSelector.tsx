import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect, LemonSelectSection, Spinner } from '@posthog/lemon-ui'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { resolveQuickFilterOption, withSelectedOption } from './quickFilterOptions'
import { DiscoveredValuesStatus, quickFilterValuesLogic } from './quickFilterValuesLogic'

interface QuickFilterSelectorProps {
    filter: Pick<QuickFilter, 'name' | 'property_name' | 'type' | 'options'>
    context: QuickFilterContext
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function QuickFilterSelector({
    filter,
    context,
    selectedOptionId,
    onChange,
}: QuickFilterSelectorProps): JSX.Element {
    if (filter.type === 'auto-discovery') {
        return (
            <DiscoveredValuesSelector
                filter={filter}
                context={context}
                selectedOptionId={selectedOptionId}
                onChange={onChange}
            />
        )
    }
    return (
        <QuickFilterOptionsSelect
            filter={filter}
            options={filter.options}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
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
    const { discoveredOptions, discoveredValuesStatus } = useValues(valuesLogic)
    const { setSearch } = useActions(valuesLogic)
    const options = useMemo(
        () => withSelectedOption(discoveredOptions, selectedOptionId),
        [discoveredOptions, selectedOptionId]
    )

    return (
        <QuickFilterOptionsSelect
            filter={filter}
            options={options}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
            discoveredValuesStatus={discoveredValuesStatus}
            onOpen={() => setSearch('')}
        />
    )
}

function discoveredValuesFooter(status: DiscoveredValuesStatus, optionCount: number): JSX.Element | string | undefined {
    if (status === 'loading') {
        return (
            <span className="flex items-center gap-1">
                <Spinner textColored />
                Loading values…
            </span>
        )
    }
    if (status === 'error') {
        return "Couldn't load values. Close and reopen the dropdown to try again."
    }
    return optionCount === 0 ? 'No values found in the last 7 days.' : undefined
}

function QuickFilterOptionsSelect({
    filter,
    options,
    selectedOptionId,
    onChange,
    discoveredValuesStatus,
    onOpen,
}: Omit<QuickFilterSelectorProps, 'context'> & {
    options: QuickFilterOption[]
    discoveredValuesStatus?: DiscoveredValuesStatus
    onOpen?: () => void
}): JSX.Element {
    const label = filter.name || 'Filter name'
    const sections = useMemo(
        (): LemonSelectSection<string | null>[] => [
            {
                options: [
                    { value: null, label: `Any ${filter.name.toLowerCase() || 'items'}` },
                    ...options.map((opt) => ({
                        value: opt.id,
                        label: opt.label,
                    })),
                ],
                footer: discoveredValuesStatus
                    ? discoveredValuesFooter(discoveredValuesStatus, options.length)
                    : undefined,
            },
        ],
        [options, filter.name, discoveredValuesStatus]
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
                onChange(selectedId === null ? null : resolveQuickFilterOption({ ...filter, options }, selectedId))
            }}
            options={sections}
            size="small"
            placeholder={label}
            dropdownMatchSelectWidth={false}
            truncateText={{ maxWidthClass: 'max-w-60' }}
            menu={onOpen ? { onVisibilityChange: (visible) => visible && onOpen() } : undefined}
        />
    )
}
