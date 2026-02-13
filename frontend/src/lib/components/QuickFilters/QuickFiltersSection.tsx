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
import {
    PropertyOperator,
    QuickFilter,
    QuickFilterOption,
    isAutoDiscoveryQuickFilter,
    isManualQuickFilter,
} from '~/types'

import { DynamicQuickFilterSelector } from './DynamicQuickFilterSelector'
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

                if (isAutoDiscoveryQuickFilter(filter)) {
                    return (
                        <DynamicQuickFilterSelector
                            key={filter.id}
                            label={filter.name}
                            propertyName={filter.property_name}
                            regexPattern={filter.options.regex_pattern}
                            operator={filter.options.operator as PropertyOperator}
                            selectedValue={(selectedFilter?.value as string) ?? null}
                            onChange={(value, operator) => {
                                if (value === null) {
                                    clearQuickFilter(filter.property_name)
                                } else {
                                    setQuickFilterValue(filter.property_name, {
                                        id: value,
                                        value,
                                        label: value,
                                        operator,
                                    })
                                }
                            }}
                        />
                    )
                }

                if (isManualQuickFilter(filter)) {
                    return (
                        <QuickFilterSelector
                            key={filter.id}
                            label={filter.name}
                            options={filter.options as QuickFilterOption[]}
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
                }

                return null
            })}
            <LemonButton size="small" icon={<IconGear />} onClick={openModal}>
                Configure quick filters
            </LemonButton>
            <QuickFiltersModal context={context} />
        </>
    )
}
