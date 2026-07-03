import type { ReactNode } from 'react'
import { useMemo } from 'react'

import type { QuickFilter } from '~/types'

import type { WidgetFilterConfigRecord } from '../generated/widget-configs.zod'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../widget_types/widgetConfigShared'

export function WidgetTileFiltersBar({ children, dataAttr }: { children: ReactNode; dataAttr: string }): JSX.Element {
    return (
        <div
            className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-2 border-b border-primary"
            data-attr={dataAttr}
            onMouseDown={(event) => event.stopPropagation()}
        >
            {children}
        </div>
    )
}

export function WidgetTileFilterReadOnlyValue({ children }: { children: ReactNode }): JSX.Element {
    return <span className="inline-flex items-center gap-1.5 text-xs text-primary">{children}</span>
}

export function WidgetTileFilterReadOnlyLabel({ name, value }: { name: string; value: string }): JSX.Element {
    return (
        <WidgetTileFilterReadOnlyValue>
            <span className="text-secondary">{name}:</span> {value}
        </WidgetTileFilterReadOnlyValue>
    )
}

export function WidgetDateRangeReadOnlyValue({ dateFrom }: { dateFrom: WidgetDateFromValue }): JSX.Element {
    const label = WIDGET_DATE_RANGE_SELECT_OPTIONS.find((option) => option.value === dateFrom)?.label ?? dateFrom
    return <WidgetTileFilterReadOnlyValue>{label}</WidgetTileFilterReadOnlyValue>
}

function widgetFilterReadOnlyLabel(
    filter: QuickFilter,
    entry: { optionId: string; value?: string | string[] | null }
): string {
    const option = filter.options.find((opt) => opt.id === entry.optionId)
    return option?.label ?? String(entry.value ?? '')
}

export function WidgetPropertyFiltersReadOnlyValues({
    filterDefinitions,
    widgetFilters,
}: {
    filterDefinitions: QuickFilter[]
    widgetFilters: WidgetFilterConfigRecord | undefined
}): JSX.Element | null {
    const stored = widgetFilters ?? {}

    const labels = useMemo(() => {
        return filterDefinitions
            .map((filter) => {
                const entry = stored[filter.id]
                if (!entry) {
                    return null
                }
                return { id: filter.id, name: filter.name, value: widgetFilterReadOnlyLabel(filter, entry) }
            })
            .filter((item): item is { id: string; name: string; value: string } => item != null)
    }, [filterDefinitions, stored])

    if (labels.length === 0) {
        return null
    }

    return (
        <>
            {labels.map((item) => (
                <WidgetTileFilterReadOnlyLabel key={item.id} name={item.name} value={item.value} />
            ))}
        </>
    )
}
