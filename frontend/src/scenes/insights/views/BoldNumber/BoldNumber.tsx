import { useActions, useValues } from 'kea'
import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'

import { ChartParams, TrendResult } from '~/types'
import { insightLogic } from '../../insightLogic'
import { Textfit } from 'react-textfit'

import './BoldNumber.scss'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import clsx from 'clsx'
import { ensureTooltipElement } from '../LineGraph/LineGraph'
import { groupsModel } from '~/models/groupsModel'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { IconTrendingDown, IconTrendingFlat, IconTrendingUp } from 'lib/components/icons'
import { LemonRow } from '@posthog/lemon-ui'
import { percentage } from 'lib/utils'

/** The tooltip is offset by a few pixels from the cursor to give it some breathing room. */
const BOLD_NUMBER_TOOLTIP_OFFSET_PX = 8

function useBoldNumberTooltip({
    showPersonsModal,
    isTooltipShown,
}: {
    showPersonsModal: boolean
    isTooltipShown: boolean
}): React.RefObject<HTMLDivElement> {
    const { filters, insight } = useValues(insightLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const divRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const divRect = divRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'

        const seriesResult = insight.result[0]

        ReactDOM.render(
            <InsightTooltip
                renderCount={(value: number) => (
                    <>{formatAggregationAxisValue(filters.aggregation_axis_format, value)}</>
                )}
                seriesData={[
                    {
                        dataIndex: 1,
                        datasetIndex: 1,
                        id: 1,
                        label: seriesResult.label,
                        count: seriesResult.aggregated_value,
                    },
                ]}
                showHeader={false}
                renderSeries={(value: React.ReactNode) => <span className="font-semibold">{value}</span>}
                hideColorCol
                hideInspectActorsSection={!showPersonsModal}
                groupTypeLabel={aggregationLabel(toLocalFilters(filters)[0].math_group_type_index).plural}
            />,
            tooltipEl,
            () => {
                const tooltipRect = tooltipEl.getBoundingClientRect()
                if (divRect) {
                    tooltipEl.style.top = `${
                        window.scrollY + divRect.top - tooltipRect.height - BOLD_NUMBER_TOOLTIP_OFFSET_PX
                    }px`
                    tooltipEl.style.left = `${divRect.left + divRect.width / 2 - tooltipRect.width / 2}px`
                }
            }
        )
    }, [isTooltipShown])

    return divRef
}

export function BoldNumber({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insight, filters } = useValues(insightLogic)
    const { loadPeople } = useActions(personsModalLogic)

    const [isTooltipShown, setIsTooltipShown] = useState(false)
    const valueRef = useBoldNumberTooltip({ showPersonsModal, isTooltipShown })

    const showComparison = filters.compare && insight.result.length > 1
    const resultSeries = insight.result[0] as TrendResult

    return (
        <div className="BoldNumber">
            <Textfit mode="single" min={32} max={120}>
                <div
                    className={clsx('BoldNumber__value', showPersonsModal ? 'cursor-pointer' : 'cursor-default')}
                    onClick={
                        showPersonsModal
                            ? () => {
                                  loadPeople({
                                      action: resultSeries.action,
                                      label: resultSeries.label,
                                      date_from: resultSeries.filter?.date_from as string,
                                      date_to: resultSeries.filter?.date_to as string,
                                      filters,
                                      saveOriginal: true,
                                      pointValue: resultSeries.aggregated_value,
                                  })
                              }
                            : undefined
                    }
                    onMouseLeave={() => setIsTooltipShown(false)}
                    ref={valueRef}
                    onMouseEnter={() => setIsTooltipShown(true)}
                >
                    {formatAggregationAxisValue(filters.aggregation_axis_format, resultSeries.aggregated_value)}
                </div>
            </Textfit>
            {showComparison && <BoldNumberComparison showPersonsModal={showPersonsModal} />}
        </div>
    )
}

function BoldNumberComparison({ showPersonsModal }: Pick<ChartParams, 'showPersonsModal'>): JSX.Element {
    const { insight, filters } = useValues(insightLogic)
    const { loadPeople } = useActions(personsModalLogic)

    const [currentPeriodSeries, previousPeriodSeries] = insight.result as TrendResult[]

    const percentageDiff = currentPeriodSeries.aggregated_value / previousPeriodSeries.aggregated_value - 1
    const percentageDiffDisplay = percentageDiff !== 0 ? percentage(Math.abs(percentageDiff)) : 'No change'
    const Icon = percentageDiff > 0 ? IconTrendingUp : percentageDiff < 0 ? IconTrendingDown : IconTrendingFlat
    const status = percentageDiff > 0 ? 'success' : percentageDiff < 0 ? 'danger' : undefined

    return (
        <LemonRow icon={<Icon />} status={status} className="BoldNumber__comparison" fullWidth center>
            <span>
                <span className={status ? `text-${status}` : undefined}>{percentageDiffDisplay}</span> from{' '}
                {showPersonsModal ? (
                    <a
                        onClick={() => {
                            loadPeople({
                                action: previousPeriodSeries.action,
                                label: previousPeriodSeries.label,
                                date_from: previousPeriodSeries.filter?.date_from as string,
                                date_to: previousPeriodSeries.filter?.date_to as string,
                                filters,
                                saveOriginal: true,
                                pointValue: previousPeriodSeries.aggregated_value,
                            })
                        }}
                    >
                        previous period
                    </a>
                ) : (
                    'previous period'
                )}
            </span>
        </LemonRow>
    )
}
