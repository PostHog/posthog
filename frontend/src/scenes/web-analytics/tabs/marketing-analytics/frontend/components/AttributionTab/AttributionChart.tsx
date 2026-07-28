import { useMemo } from 'react'

import type { Series } from '@posthog/quill-charts'
import { BarChart, useChartTheme } from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AttributionMode, MarketingAnalyticsAttributionRow } from '~/queries/schema/schema-general'

import { MODEL_LABELS } from '../../logic/marketingAttributionLogic'

// The chart scrolls horizontally, so the cap only guards against absurd band counts (a landing-page
// breakdown can have hundreds of values); the table below still has every row.
const MAX_CHART_ROWS = 30

// Below this width per band, five grouped bars squish into unreadable slivers; the chart scrolls
// horizontally instead of shrinking further.
const MIN_BAND_WIDTH_PX = 96

export function AttributionChart({
    rows,
    models,
    dimensionLabel,
}: {
    rows: MarketingAnalyticsAttributionRow[]
    models: AttributionMode[]
    dimensionLabel: string
}): JSX.Element | null {
    const theme = useChartTheme()

    // Rows arrive server-ordered by influenced conversions, so the slice is the top slice.
    const chartRows = useMemo(() => rows.slice(0, MAX_CHART_ROWS), [rows])

    const series: Series[] = useMemo(
        () =>
            models.map((model, index) => ({
                key: model,
                label: MODEL_LABELS[model],
                data: chartRows.map((row) => row.models[index]?.conversions ?? 0),
            })),
        [models, chartRows]
    )

    if (!chartRows.length) {
        return null
    }

    return (
        <div className="rounded border bg-surface-primary p-4">
            <h3 className="mb-0 text-base font-semibold">Conversions by attribution model</h3>
            <p className="mb-2 text-secondary">
                Each bar is the number of conversions a model credits to a {dimensionLabel.toLowerCase()}. Bars of equal
                height mean the models agree; different heights show where credit moves when the model changes.
                {rows.length > MAX_CHART_ROWS
                    ? ` Showing the top ${MAX_CHART_ROWS} of ${rows.length} rows. The table below has all of them.`
                    : ''}
            </p>
            {/* Flex column, not a plain block: with a legend enabled the chart root is a `flex-1
                min-h-0` legend layout, which only resolves to a real height inside a flex parent. */}
            <div className="h-80 overflow-x-auto">
                <div
                    className="flex h-full flex-col"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ minWidth: `max(100%, ${chartRows.length * MIN_BAND_WIDTH_PX}px)` }}
                >
                    <BarChart
                        series={series}
                        labels={chartRows.map((row) => row.breakdownValue || '(none)')}
                        theme={theme}
                        config={{
                            barLayout: 'grouped',
                            legend: { show: true, position: 'top' },
                            tooltip: {
                                valueFormatter: (value: number) => humanFriendlyNumber(value, 1),
                                sortedByValue: true,
                            },
                        }}
                    />
                </div>
            </div>
        </div>
    )
}
