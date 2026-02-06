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
    logicKey?: string
    /** Key to scope modal logic instance (e.g. per dashboard) */
    modalKey?: string | number
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

export function QuickFiltersButton({
    context,
    modalKey,
    onNewFilterCreated,
}: Pick<QuickFiltersSectionProps, 'context' | 'modalKey' | 'onNewFilterCreated'>): JSX.Element {
    const logicProps = { context, modalKey, onNewFilterCreated }
    const { openModal } = useActions(quickFiltersModalLogic(logicProps))

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconFilter />}
                onClick={openModal}
                tooltip="Configure quick filters"
                aria-label="Configure quick filters"
            />
            <QuickFiltersModal {...logicProps} />
        </>
    )
}

// Display selected quick filters
export function QuickFiltersSelectors({
    context,
    logicKey,
    filterIds,
}: Pick<QuickFiltersSectionProps, 'context' | 'logicKey' | 'filterIds'>): JSX.Element | null {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context, logicKey }))
    const { setQuickFilterValue, clearQuickFilter } = useActions(quickFiltersSectionLogic({ context, logicKey }))

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

export function QuickFiltersSection({
    context,
    logicKey,
    modalKey,
    onNewFilterCreated,
    filterIds,
}: QuickFiltersSectionProps): JSX.Element {
    return (
        <>
            <QuickFiltersSelectors context={context} logicKey={logicKey} filterIds={filterIds} />
            <QuickFiltersButton context={context} modalKey={modalKey} onNewFilterCreated={onNewFilterCreated} />
        </>
    )
}
