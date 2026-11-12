import { useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'
import { ChartHoverSync } from '@posthog/quill-charts'

import { cn } from 'lib/utils/css-classes'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'

import type { MetricsTableWidgetConfig } from '../../generated/widget-configs.zod'
import { buildMetricsTableDrilldown, type MetricsTableDrilldownDashboardFilters } from './metricsTableDrilldown'
import { metricsTableGroupByLabels } from './metricsTableWidgetConfigValidation'

const INTERVAL_LABELS: Record<string, string> = {
    minute: 'minute',
    minute_5: '5 minutes',
    minute_15: '15 minutes',
    minute_30: '30 minutes',
    hour: 'hour',
    hour_6: '6 hours',
    day: 'day',
    week: 'week',
}

/** Two or four charts read best as a square, every other count as rows of three, so most tables fit one screen. */
function gridColumnsClass(chartCount: number): string {
    if (chartCount <= 1) {
        return ''
    }
    if (chartCount === 2 || chartCount === 4) {
        return '@min-[40rem]:grid-cols-2'
    }
    return '@min-[40rem]:grid-cols-2 @min-[64rem]:grid-cols-3'
}

export function MetricsTableDrilldownModal({
    config,
    names,
    dashboardFilters,
    labelValues,
    onClose,
}: {
    config: MetricsTableWidgetConfig
    names: string[]
    dashboardFilters?: MetricsTableDrilldownDashboardFilters | null
    /** The label values of each row in `names`, in the order of the config's group-by labels. */
    labelValues: string[][]
    onClose: () => void
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    if (names.length === 0) {
        return null
    }
    const { dateFrom, dateTo, interval, charts } = buildMetricsTableDrilldown(
        config,
        labelValues,
        dashboardFilters,
        timezone
    )
    const rangeText = dateFilterToText(dateFrom, dateTo, 'Last hour')
    const intervalLabel = interval ? INTERVAL_LABELS[interval] : undefined
    return (
        <LemonModal
            isOpen
            onClose={onClose}
            width={1200}
            title={
                names.length === 1
                    ? names[0]
                    : `${names.length} ${metricsTableGroupByLabels(config.groupBy).join(' · ')} values`
            }
            description={names.length === 1 ? undefined : names.join(', ')}
        >
            <div className="flex flex-col gap-3" data-attr="metrics-table-widget-drilldown">
                <p className="m-0 text-xs text-secondary" data-attr="metrics-table-widget-drilldown-range">
                    {intervalLabel ? `${rangeText}, one point every ${intervalLabel}` : rangeText}
                </p>
                {/* Hovering one chart draws a crosshair at the same time on the others, so a spike lines up across columns. */}
                <ChartHoverSync>
                    <div className="@container">
                        <div className={cn('grid grid-cols-1 gap-4', gridColumnsClass(charts.length))}>
                            {charts.map((chart, index) => (
                                <section key={index} className="flex min-w-0 flex-col gap-1">
                                    <h5 className="m-0 truncate text-sm font-semibold">{chart.title}</h5>
                                    <div className="flex h-52 flex-col">
                                        <Query query={chart.query} readOnly embedded />
                                    </div>
                                </section>
                            ))}
                        </div>
                    </div>
                </ChartHoverSync>
            </div>
        </LemonModal>
    )
}
