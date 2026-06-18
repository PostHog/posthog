import clsx from 'clsx'
import { useValues } from 'kea'

import { MetricCard, useChartTheme } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'

export function Metric({ showPersonsModal = true, inCardView, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { baseCurrency } = useValues(teamLogic)
    const theme = useChartTheme()

    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    if (!resultSeries) {
        return <InsightEmptyState />
    }

    // The Metric headline is the metric over the period (the series total); the sparkline shows its movement.
    const headlineValue = resultSeries.count

    const goodDirection = trendsFilter?.metricGoodDirection ?? 'up'
    const showChange = trendsFilter?.metricShowChange ?? true

    // The sparkline's hover/resting subtitle is the point's date — format it the app's way ("June 16, 2026")
    // rather than the raw backend label ("16-Jun-2026").
    const labels = resultSeries.days?.map((day) => formatDate(dayjs(day))) ?? resultSeries.labels

    const handleClick = context?.onDataPointClick
        ? () => context?.onDataPointClick?.({ compare: 'current' }, resultSeries)
        : showPersonsModal && headlineValue != null && !hasDataWarehouseSeries // != is intentional to catch undefined too
          ? () => {
                openPersonsModal({
                    title: resultSeries.label,
                    query: {
                        kind: NodeKind.InsightActorsQuery,
                        source: querySource!,
                        includeRecordings: true,
                    },
                    additionalSelect: {
                        value_at_data_point: 'event_count',
                        matched_recordings: 'matched_recordings',
                    },
                    orderBy: ['event_count DESC, actor_id DESC'],
                })
            }
          : undefined

    // Left-aligned, full-width tile: the sparkline fills the width and the pill is derived from the series itself
    // (first → last of the period) by MetricCard — it does not depend on the "Compare to previous" filter.
    // On a dashboard card the content fills the height (value/pill at the top, sparkline grows to fill the rest);
    // in the insight view the tile is content-height at the top.
    return (
        <div className={clsx('Metric ph-no-capture flex flex-col w-full p-4', inCardView && 'flex-1')}>
            <MetricCard
                // Fill the card height so the sparkline can grow into the remaining space.
                className={inCardView ? 'flex-1' : undefined}
                sparklineFill={inCardView}
                // No title: the insight/card already shows the name above. In a card the change pill goes inline
                // next to the value; in the insight view it sits top-right.
                title={null}
                value={headlineValue}
                changeSize="md"
                changeInline={inCardView}
                data={resultSeries.data}
                labels={labels}
                theme={theme}
                goodDirection={goodDirection}
                showChange={showChange}
                formatValue={(value) => formatAggregationAxisValue(trendsFilter, value, baseCurrency)}
                sparklineHeight={120}
                // Bleed the sparkline to the left/right edges; keep it directly under the value.
                sparklineClassName="mt-4 -mx-4"
                headline={(formattedValue) => (
                    <div
                        className={clsx(
                            'text-4xl font-bold tracking-tight tabular-nums',
                            // Inline with the pill in card view; below the header row otherwise.
                            !inCardView && 'mt-2',
                            showPersonsModal ? 'cursor-pointer' : 'cursor-default'
                        )}
                        data-attr="bold-number-value"
                        onClick={handleClick}
                    >
                        {formattedValue}
                    </div>
                )}
            />
        </div>
    )
}
