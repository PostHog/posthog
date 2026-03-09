import { useValues } from 'kea'

import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import type { ClickEvent } from 'lib/hog-charts'
import { isMultiSeriesFormula } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { ChartParams } from '~/types'

import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'
import { datasetToActorsQuery } from './datasetToActorsQuery'

/**
 * Builds the click handler for a trends chart data point.
 * Returns undefined when clicks are not actionable (no persons modal, formula series, etc.).
 */
export function useTrendsChartClick({
    showPersonsModal = true,
    context,
}: {
    showPersonsModal: boolean
    context: ChartParams['context']
}): ((event: ClickEvent) => void) | undefined {
    const { insightProps } = useValues(insightLogic)
    const {
        indexedResults,
        formula,
        interval,
        isLifecycle,
        isStickiness,
        hasDataWarehouseSeries,
        querySource,
        insightData,
    } = useValues(trendsDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)

    const canClick =
        !!context?.onDataPointClick || (showPersonsModal && !isMultiSeriesFormula(formula) && !hasDataWarehouseSeries)

    if (!canClick) {
        return undefined
    }

    return (event: ClickEvent): void => {
        if (!event.meta) {
            return
        }

        const dataset = event.meta._dataset as
            | ((typeof indexedResults)[number] & { breakdownValues?: string[]; compareLabels?: string[] })
            | undefined
        if (!dataset) {
            return
        }

        const day = dataset.action?.days?.[event.pointIndex] ?? dataset.days?.[event.pointIndex] ?? ''
        const label = dataset.label ?? dataset.labels?.[event.pointIndex] ?? ''

        if (context?.onDataPointClick) {
            context.onDataPointClick(
                {
                    breakdown: dataset.breakdownValues?.[event.pointIndex],
                    compare: dataset.compareLabels?.[event.pointIndex] || undefined,
                    day,
                },
                indexedResults[0]
            )
            return
        }

        if (!showPersonsModal || isMultiSeriesFormula(formula) || hasDataWarehouseSeries) {
            return
        }

        const title = isStickiness ? (
            <>
                <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on {interval || 'day'} {day}
            </>
        ) : (
            (titleLabel: string) => (
                <>
                    {titleLabel} on{' '}
                    <DateDisplay
                        interval={interval || 'day'}
                        resolvedDateRange={insightData?.resolved_date_range}
                        timezone={timezone}
                        weekStartDay={weekStartDay}
                        date={day?.toString() || ''}
                    />
                </>
            )
        )

        openPersonsModal({
            title,
            query: datasetToActorsQuery({ dataset, query: querySource!, day }),
            additionalSelect:
                isLifecycle || isStickiness
                    ? {}
                    : {
                          value_at_data_point: 'event_count',
                          matched_recordings: 'matched_recordings',
                      },
            orderBy: isLifecycle || isStickiness ? undefined : ['event_count DESC, actor_id DESC'],
        })
    }
}
