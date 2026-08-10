import clsx from 'clsx'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import type { BarChartConfig, Series } from '@posthog/quill-charts'
import { BarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AttributionMode, MarketingAnalyticsAttributionRow } from '~/queries/schema/schema-general'

import { MODEL_LABELS } from '../../logic/marketingAttributionLogic'

// A landing-page breakdown can have hundreds of values; the table below still has every row.
const MAX_CHART_ROWS = 30

// Below this, five grouped bars squish into unreadable slivers, so the chart scrolls instead.
const MIN_BAND_WIDTH_PX = 96

const SKELETON_BAR_HEIGHTS = ['h-48', 'h-40', 'h-32', 'h-28', 'h-20', 'h-16', 'h-12', 'h-8']

// The response carries the model list, so a first load has nothing to count yet.
const SKELETON_SERIES_COUNT = 5

function ChartSkeleton({ modelCount }: { modelCount: number }): JSX.Element {
    return (
        <div className="flex h-full flex-col gap-3" aria-busy="true">
            <div className="flex items-center justify-center gap-4">
                {Array.from({ length: modelCount }, (_, i) => (
                    <LemonSkeleton key={i} className="h-3 w-16" />
                ))}
            </div>
            <div className="flex flex-1 items-end justify-around gap-4 pb-5">
                {SKELETON_BAR_HEIGHTS.map((height, band) => (
                    <div key={band} className="flex items-end gap-1">
                        {Array.from({ length: modelCount }, (_, i) => (
                            <LemonSkeleton key={i} className={clsx('w-2.5', height)} />
                        ))}
                    </div>
                ))}
            </div>
        </div>
    )
}

export function AttributionChart({
    rows,
    models,
    dimensionLabel,
    loading,
}: {
    rows: MarketingAnalyticsAttributionRow[]
    models: AttributionMode[]
    dimensionLabel: string
    loading?: boolean
}): JSX.Element | null {
    const theme = useChartTheme()

    // Rows arrive server-ordered by influenced conversions, so the slice is the top slice.
    const chartRows = useMemo(() => rows.slice(0, MAX_CHART_ROWS), [rows])

    const config: BarChartConfig = useChartConfig(
        () => ({
            barLayout: 'grouped',
            legend: { show: true, position: 'top' },
            tooltip: {
                valueFormatter: (value: number) => humanFriendlyNumber(value, 1),
                sortedByValue: true,
            },
        }),
        []
    )

    const series: Series[] = useMemo(
        () =>
            models.map((model, index) => ({
                key: model,
                label: MODEL_LABELS[model],
                data: chartRows.map((row) => row.models[index]?.conversions ?? 0),
            })),
        [models, chartRows]
    )

    // Only a settled empty result hides the card: collapsing while loading shoves the table upward.
    if (!loading && !chartRows.length) {
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
            {/* Flex column, not a plain block: with a legend the chart root is a `flex-1 min-h-0`
                layout, which only resolves to a real height inside a flex parent. */}
            <div className="h-80 overflow-x-auto">
                {chartRows.length ? (
                    <div
                        // A refetch fades the previous bars rather than replacing a readable chart with
                        // a placeholder.
                        className={clsx('flex h-full flex-col', loading && 'opacity-50 transition-opacity')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ minWidth: `max(100%, ${chartRows.length * MIN_BAND_WIDTH_PX}px)` }}
                    >
                        <BarChart
                            series={series}
                            labels={chartRows.map((row) => row.breakdownValue || '(none)')}
                            theme={theme}
                            config={config}
                        />
                    </div>
                ) : (
                    <ChartSkeleton modelCount={models.length || SKELETON_SERIES_COUNT} />
                )}
            </div>
        </div>
    )
}
