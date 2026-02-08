import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
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
}

export function QuickFiltersSection({ context }: QuickFiltersSectionProps): JSX.Element {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context }))
    const { setQuickFilterValue, clearQuickFilter } = useActions(quickFiltersSectionLogic({ context }))
    const { openModal } = useActions(quickFiltersModalLogic({ context }))

    return (
        <>
            {quickFilters.map((filter: QuickFilter) => {
                const selectedFilter = selectedQuickFilters[filter.property_name]

                return (
                    <QuickFilterSelector
                        key={filter.id}
                        label={filter.name}
                        options={filter.options}
                        selectedOptionId={selectedFilter?.optionId || null}
                        onChange={(option) => {
                            if (option === null) {
                                clearQuickFilter(filter.property_name)
                            } else {
                                setQuickFilterValue(filter.property_name, option)
                            }
                        }}
                    />
                )
            })}
            <LemonButton size="small" icon={<IconGear />} onClick={openModal}>
                Configure quick filters
            </LemonButton>
            <QuickFiltersModal context={context} />
        </>
    )
}
