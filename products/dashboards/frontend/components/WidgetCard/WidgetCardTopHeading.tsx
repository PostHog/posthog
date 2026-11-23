import { Suspense } from 'react'

import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { dateFilterToText } from 'lib/utils/dateFilters'

import type { DashboardWidgetHeaderMeta } from '../../widget_types/catalog'
import { LiveWidgetIndicator } from '../../widgets/live/components'
import type { DashboardWidgetSlot } from '../../widgets/registry'

/** Props a widget type's optional TopHeading override receives so it can compose its own
 * CardTopHeadingRow — e.g. resolving a saved filter's name the generic header can't derive from config. */
export type DashboardWidgetTopHeadingProps = {
    config: Record<string, unknown>
    widgetTypeLabel?: string
    showWidgetType: boolean
    dateText?: string | null
}

export type WidgetCardTopHeadingProps = {
    widgetTypeLabel?: string
    config?: Record<string, unknown>
    headerMeta?: DashboardWidgetHeaderMeta
    /** Optional per-widget-type top heading row; falls back to the type + date range when absent.
     * A `DashboardWidgetSlot` so the registry can code-split it (rendered inside a Suspense below). */
    TopHeading?: DashboardWidgetSlot<DashboardWidgetTopHeadingProps>
    /** Live (self-updating) widget type — shows a pulsing "Live" marker where the date range would go. */
    isLive?: boolean
}

export function WidgetCardTopHeading({
    widgetTypeLabel,
    config,
    headerMeta,
    TopHeading,
    isLive,
}: WidgetCardTopHeadingProps): JSX.Element | null {
    const showWidgetType = headerMeta?.showWidgetType ?? true
    const showDateRange = headerMeta?.showDateRange ?? false
    const dateText =
        widgetTypeLabel && showDateRange
            ? widgetDateRangeToText(config?.dateRange as Record<string, unknown> | null | undefined)
            : null

    if (!widgetTypeLabel || !(showWidgetType || dateText || isLive)) {
        return null
    }

    // A widget type can supply its own top heading row (e.g. session replay surfaces the active
    // saved filter name in place of the now-overridden date range); otherwise fall back to the
    // type + date range (or the live marker — live widgets have no date range).
    return TopHeading ? (
        <Suspense fallback={null}>
            <TopHeading
                config={config ?? {}}
                widgetTypeLabel={widgetTypeLabel}
                showWidgetType={showWidgetType}
                dateText={dateText}
            />
        </Suspense>
    ) : (
        <CardTopHeadingRow
            typeLabel={widgetTypeLabel}
            showTypeLabel={showWidgetType}
            dateText={dateText}
            separateChildren
        >
            {isLive ? <LiveWidgetIndicator /> : null}
        </CardTopHeadingRow>
    )
}

function widgetDateRangeToText(
    dateRange: Record<string, unknown> | null | undefined,
    defaultValue: string | null = 'Last 7 days'
): string | null {
    if (!dateRange || typeof dateRange !== 'object') {
        return defaultValue
    }

    const dateFrom = 'date_from' in dateRange ? (dateRange.date_from as string | null | undefined) : undefined
    const dateTo = 'date_to' in dateRange ? (dateRange.date_to as string | null | undefined) : undefined

    if (!dateFrom && !dateTo) {
        return defaultValue
    }

    return dateFilterToText(dateFrom, dateTo, defaultValue)
}
