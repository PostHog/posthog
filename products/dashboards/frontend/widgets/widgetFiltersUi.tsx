import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'

import type { QuickFilter } from '~/types'

import type { WidgetFilterConfigRecord } from '../widget_types/configSchemas'
import { errorTrackingWidgetFiltersSetup } from './widgetFilters'

export function buildWidgetFilterChipEntries(
    filterDefinitions: QuickFilter[],
    widgetFilters: WidgetFilterConfigRecord
): { key: string; label: ReactNode }[] {
    return Object.values(widgetFilters).map((entry) => {
        const definition = filterDefinitions.find((filter) => filter.id === entry.filterId)
        const option = definition?.options.find((opt) => opt.id === entry.optionId)
        const filterLabel = definition?.name ?? entry.propertyName
        const valueLabel = option?.label ?? (Array.isArray(entry.value) ? entry.value.join(', ') : entry.value)
        return {
            key: entry.filterId,
            label: valueLabel ? `${filterLabel}: ${valueLabel}` : filterLabel,
        }
    })
}

export type WidgetFilterChipsProps = {
    setup: Pick<typeof errorTrackingWidgetFiltersSetup, 'context'>
    widgetFilters: WidgetFilterConfigRecord
    className?: string
    'data-attr'?: string
}

export function WidgetFilterChips({
    setup,
    widgetFilters,
    className = 'flex flex-wrap gap-1.5 px-3 py-2 border-b border-primary min-w-0',
    'data-attr': dataAttr = 'widget-filter-chips',
}: WidgetFilterChipsProps): JSX.Element | null {
    const { quickFilters: filterDefinitions } = useValues(quickFiltersLogic({ context: setup.context }))
    const chips = buildWidgetFilterChipEntries(filterDefinitions, widgetFilters)

    if (chips.length === 0) {
        return null
    }

    return (
        <div className={className} data-attr={dataAttr}>
            {chips.map((chip) => (
                <LemonTag key={chip.key} type="muted" size="small">
                    {chip.label}
                </LemonTag>
            ))}
        </div>
    )
}
