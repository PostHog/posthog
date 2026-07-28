import clsx from 'clsx'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
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

// Descending so the placeholder reads as a ranked chart, which is what actually arrives. Fixed rather
// than random: a placeholder that reshuffles on every render draws the eye to the wrong thing.
const SKELETON_BAR_HEIGHTS = ['h-48', 'h-40', 'h-32', 'h-28', 'h-20', 'h-16', 'h-12', 'h-8']

// The response carries the model list, so on a first load there's nothing to count yet. Five is the
// number of models the runner always returns.
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

    const series: Series[] = useMemo(
        () =>
            models.map((model, index) => ({
                key: model,
                label: MODEL_LABELS[model],
                data: chartRows.map((row) => row.models[index]?.conversions ?? 0),
            })),
        [models, chartRows]
    )

    // Only a settled empty result hides the card. While loading the card stays mounted at its full
    // height, so switching breakdown or date doesn't collapse the page and shove the table upward.
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
            {/* Flex column, not a plain block: with a legend enabled the chart root is a `flex-1
                min-h-0` legend layout, which only resolves to a real height inside a flex parent. */}
            <div className="h-80 overflow-x-auto">
                {chartRows.length ? (
                    <div
                        // A refetch keeps the previous bars and just fades them, rather than replacing a
                        // chart the user is reading with a placeholder they can't read.
                        className={clsx('flex h-full flex-col', loading && 'opacity-50 transition-opacity')}
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
                ) : (
                    <ChartSkeleton modelCount={models.length || SKELETON_SERIES_COUNT} />
                )}
            </div>
        </div>
    )
}
