import { useValues } from 'kea'

import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import type { ClickEvent } from 'lib/hog-charts'
import { isMultiSeriesFormula } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import type { ChartParams, GraphDataset, IntervalType } from '~/types'

import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'
import { datasetToActorsQuery } from './datasetToActorsQuery'

/**
 * Builds the click handler for a trends chart data point.
 * Returns undefined when clicks are not actionable (no persons modal, formula series, etc.).
 */
export function useTrendsPersonsModal({
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
        const meta = event.meta
        if (!meta) {
            return
        }

        const day = event.label
        const breakdownValues = meta.breakdownValues as string[] | undefined
        const compareLabels = meta.compareLabels as ('previous' | 'current')[] | undefined

        if (context?.onDataPointClick) {
            return context.onDataPointClick(
                {
                    breakdown: breakdownValues?.[event.pointIndex],
                    compare: compareLabels?.[event.pointIndex] || undefined,
                    day,
                },
                indexedResults[0]
            )
        }

        openPersonsModal({
            title: (
                <PersonsModalTitle
                    label={event.seriesLabel}
                    isStickiness={isStickiness}
                    interval={interval ?? 'day'}
                    day={day}
                    resolvedDateRange={insightData?.resolved_date_range}
                    timezone={timezone}
                    weekStartDay={weekStartDay}
                />
            ),
            query: datasetToActorsQuery({
                dataset: meta as unknown as GraphDataset,
                query: querySource!,
                day,
                index: event.pointIndex,
            }),
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

function PersonsModalTitle({
    label,
    isStickiness,
    interval,
    day,
    resolvedDateRange,
    timezone,
    weekStartDay,
}: {
    label: string
    isStickiness: boolean
    interval: IntervalType
    day: string
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone: string
    weekStartDay: number
}): JSX.Element {
    if (isStickiness) {
        return (
            <>
                <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on {interval} {day}
            </>
        )
    }

    return (
        <>
            {label} on{' '}
            <DateDisplay
                interval={interval}
                resolvedDateRange={resolvedDateRange}
                timezone={timezone}
                weekStartDay={weekStartDay}
                date={day?.toString() || ''}
            />
        </>
    )
}
