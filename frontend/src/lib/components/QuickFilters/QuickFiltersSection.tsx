import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { QuickFilterSelector, quickFiltersLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter } from '~/types'

import { QuickFiltersConfigureButton } from './QuickFiltersConfigureButton'
import { quickFiltersSectionLogic } from './quickFiltersSectionLogic'

export interface QuickFiltersSectionProps {
    context: QuickFilterContext
    logicKey?: string
    /** Callback fired when a new quick filter is created while the modal is open */
    onNewFilterCreated?: (filter: QuickFilter) => void
    /**
     * Controls which filters to show:
     * - `undefined` or `null`: show all filters (default/unset behavior)
     * - `[]` (empty array): show no filters (user explicitly selected none)
     * - `['id1', 'id2']`: show only filters with matching IDs
     */
    filterIds?: string[] | null
}

export function QuickFiltersSection({
    context,
    logicKey,
    onNewFilterCreated,
    filterIds,
}: QuickFiltersSectionProps): JSX.Element {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context, logicKey }))
    const { setQuickFilterValue, clearQuickFilter } = useActions(quickFiltersSectionLogic({ context, logicKey }))

    const filtersToShow = useMemo(() => {
        if (filterIds === null || filterIds === undefined) {
            return quickFilters
        }
        return quickFilters.filter((filter: QuickFilter) => filterIds.includes(filter.id))
    }, [quickFilters, filterIds])

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
            <QuickFiltersConfigureButton
                context={context}
                onNewFilterCreated={onNewFilterCreated}
                showLabel={quickFilters.length === 0}
            />
        </>
    )
}
