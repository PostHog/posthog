import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    QuickFilterSelector,
    QuickFiltersModal,
    quickFiltersLogic,
    quickFiltersModalLogic,
} from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter } from '~/types'

import { quickFiltersSectionLogic } from './quickFiltersSectionLogic'

export interface QuickFiltersSectionProps {
    context: QuickFilterContext
    /**
     * Controls which filters to show:
     * - `undefined` or `null`: show all filters (default/unset behavior)
     * - `[]` (empty array): show no filters (user explicitly selected none)
     * - `['id1', 'id2']`: show only filters with matching IDs
     */
    filterIds?: string[] | null
}

export function QuickFiltersButton({ context }: Pick<QuickFiltersSectionProps, 'context'>): JSX.Element {
    const { openModal } = useActions(quickFiltersModalLogic({ context }))

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconFilter />}
                onClick={openModal}
                tooltip="Configure quick filters"
                aria-label="Configure quick filters"
            />
            <QuickFiltersModal context={context} />
        </>
    )
}

// Display selected quick filters
export function QuickFiltersSelectors({
    context,
    filterIds,
}: Pick<QuickFiltersSectionProps, 'context' | 'filterIds'>): JSX.Element | null {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context }))
    const { setQuickFilterValue, clearQuickFilter } = useActions(quickFiltersSectionLogic({ context }))

    const filtersToShow = useMemo(() => {
        if (filterIds === null || filterIds === undefined) {
            return quickFilters
        }
        return quickFilters.filter((filter: QuickFilter) => filterIds.includes(filter.id))
    }, [quickFilters, filterIds])

    if (filtersToShow.length === 0) {
        return null
    }

    return (
        <>
            {filtersToShow.map((filter: QuickFilter) => {
                const selectedFilter = selectedQuickFilters[filter.id]

                return (
                    <QuickFilterSelector
                        key={filter.id}
                        label={filter.name}
                        options={filter.options}
                        selectedOptionId={selectedFilter?.optionId || null}
                        onChange={(option) => {
                            if (option === null) {
                                clearQuickFilter(filter.id)
                            } else {
                                setQuickFilterValue(filter.id, filter.property_name, option)
                            }
                        }}
                    />
                )
            })}
        </>
    )
}

export function QuickFiltersSection({ context, filterIds }: QuickFiltersSectionProps): JSX.Element {
    return (
        <>
            <QuickFiltersSelectors context={context} filterIds={filterIds} />
            <QuickFiltersButton context={context} />
        </>
    )
}
