import { QuickFilterSelector } from 'lib/components/QuickFilters/QuickFilterSelector'

import type { QuickFilter } from '~/types'

import type { WidgetFilterConfigEntry, WidgetFilterConfigRecord } from '../generated/widget-configs.zod'

export type WidgetPropertyFiltersSectionProps = {
    filterDefinitions: QuickFilter[]
    widgetFilters: WidgetFilterConfigRecord
    onWidgetFiltersChange: (widgetFilters: WidgetFilterConfigRecord) => void
}

export function WidgetPropertyFiltersSection({
    filterDefinitions,
    widgetFilters,
    onWidgetFiltersChange,
}: WidgetPropertyFiltersSectionProps): JSX.Element {
    return (
        <>
            {filterDefinitions.map((filter) => {
                const entry = widgetFilters[filter.id]
                const selectedOptionId = entry?.optionId ?? null

                return (
                    <QuickFilterSelector
                        key={filter.id}
                        label={filter.name}
                        options={filter.options}
                        selectedOptionId={selectedOptionId}
                        onChange={(option) => {
                            const next = { ...widgetFilters }
                            if (option === null) {
                                delete next[filter.id]
                            } else {
                                next[filter.id] = {
                                    filterId: filter.id,
                                    propertyName: filter.property_name,
                                    optionId: option.id,
                                    operator: option.operator as WidgetFilterConfigEntry['operator'],
                                    value: option.value,
                                }
                            }
                            onWidgetFiltersChange(next)
                        }}
                    />
                )
            })}
        </>
    )
}
