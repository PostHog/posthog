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
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

/** The effect of the value's padding is reduced by the offset. */
const BOLD_NUMBER_TOOLTIP_OFFSET_PX = -16

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

        const seriesResult = insight.result?.[0]

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
                        label: seriesResult?.label,
                        count: seriesResult?.aggregated_value,
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

    const resultSeries = insight?.result?.[0] as TrendResult

    return resultSeries ? (
        <div className="BoldNumber">
            <Textfit mode="single" min={32} max={160}>
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
        </div>
    ) : (
        <InsightEmptyState />
    )
}
