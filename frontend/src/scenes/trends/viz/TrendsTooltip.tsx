import { useValues } from 'kea'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import type { TooltipContext } from 'lib/hog-charts'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'

import { trendsDataLogic } from '../trendsDataLogic'
import {
    formatTooltipCount,
    lifecycleSeriesLabel,
    resolveGroupTypeLabel,
    tooltipPointsToSeriesDatum,
} from './trendsChartUtils'

function TrendsSeriesLabel({
    value,
    datum,
    isLifecycle,
    formula,
}: {
    value: React.ReactNode
    datum: SeriesDatum
    isLifecycle: boolean
    formula: string | null | undefined
}): React.ReactNode {
    if (isLifecycle) {
        return lifecycleSeriesLabel(datum)
    }
    const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
    return (
        <div className="datum-label-column">
            {!formula && (
                <SeriesLetter
                    className="mr-2"
                    hasBreakdown={hasBreakdown}
                    seriesIndex={datum.action?.order ?? datum.id}
                    seriesColor={datum.color}
                />
            )}
            {value}
        </div>
    )
}

export function TrendsTooltip({
    context,
    showPersonsModal,
    groupTypeLabel: contextGroupTypeLabel,
}: {
    context: TooltipContext
    showPersonsModal: boolean
    groupTypeLabel?: string
}): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        indexedResults,
        trendsFilter,
        breakdownFilter,
        isLifecycle,
        isStickiness,
        isPercentStackView,
        formula,
        interval,
        insightData,
        labelGroupType,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const seriesData = tooltipPointsToSeriesDatum(context.points)
    const referencePoint = context.points[0]
    const date = (referencePoint?.meta?.days as string[])?.[referencePoint?.pointIndex] as string | undefined

    const groupTypeLabel = resolveGroupTypeLabel(contextGroupTypeLabel, labelGroupType, aggregationLabel)

    return (
        <InsightTooltip
            date={date}
            timezone={timezone}
            seriesData={seriesData}
            breakdownFilter={breakdownFilter}
            interval={interval}
            dateRange={insightData?.resolved_date_range}
            showShiftKeyHint={false}
            renderSeries={(value: React.ReactNode, datum: SeriesDatum) => (
                <TrendsSeriesLabel value={value} datum={datum} isLifecycle={isLifecycle} formula={formula} />
            )}
            renderCount={(value: number) =>
                formatTooltipCount(value, {
                    isStickiness,
                    isPercentStackView,
                    trendsFilter,
                    indexedResults,
                    seriesData,
                })
            }
            hideInspectActorsSection={!showPersonsModal}
            groupTypeLabel={groupTypeLabel}
            {...(isLifecycle ? { altTitle: 'Users', altRightTitle: (_, d) => d } : {})}
        />
    )
}
