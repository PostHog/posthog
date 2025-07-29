import './BoldNumber.scss'

import { IconTrending } from '@posthog/icons'
import { LemonRow, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconFlare, IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils'
import { useLayoutEffect, useRef, useState } from 'react'
import { useEffect } from 'react'
import React from 'react'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { groupsModel } from '~/models/groupsModel'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartParams, TrendResult } from '~/types'

import { insightLogic } from '../../insightLogic'
import { ensureTooltip } from '../LineGraph/LineGraph'
import { Textfit } from './Textfit'

/** The tooltip is offset by a few pixels from the cursor to give it some breathing room. */
const BOLD_NUMBER_TOOLTIP_OFFSET_PX = 8

function useBoldNumberTooltip({
    showPersonsModal,
    isTooltipShown,
    groupTypeLabel,
}: {
    showPersonsModal: boolean
    isTooltipShown: boolean
    groupTypeLabel?: string
}): React.RefObject<HTMLDivElement> {
    const { insightProps } = useValues(insightLogic)
    const { series, insightData, trendsFilter, breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const divRef = useRef<HTMLDivElement>(null)

    const divRect = divRef.current?.getBoundingClientRect()
    const [tooltipRoot, tooltipEl] = ensureTooltip()

    useLayoutEffect(() => {
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'

        const seriesResult = insightData?.result?.[0]

        tooltipRoot.render(
            <InsightTooltip
                renderCount={(value: number) => <>{formatAggregationAxisValue(trendsFilter, value)}</>}
                seriesData={[
                    {
                        dataIndex: 1,
                        datasetIndex: 1,
                        id: 1,
                        order: 1,
                        label: seriesResult?.label,
                        count: seriesResult?.aggregated_value,
                    },
                ]}
                breakdownFilter={breakdownFilter}
                showHeader={false}
                renderSeries={(value: React.ReactNode) => <span className="font-semibold">{value}</span>}
                hideColorCol
                hideInspectActorsSection={!showPersonsModal}
                groupTypeLabel={groupTypeLabel || aggregationLabel(series?.[0].math_group_type_index).plural}
            />
        )
    }, [isTooltipShown])

    useEffect(() => {
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (divRect) {
            tooltipEl.style.top = `${
                window.scrollY + divRect.top - tooltipRect.height - BOLD_NUMBER_TOOLTIP_OFFSET_PX
            }px`
            tooltipEl.style.left = `${divRect.left + divRect.width / 2 - tooltipRect.width / 2}px`
        }
    })

    return divRef
}

export function BoldNumber({ showPersonsModal = true, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter, compareFilter, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )

    const [isTooltipShown, setIsTooltipShown] = useState(false)
    const valueRef = useBoldNumberTooltip({ showPersonsModal, isTooltipShown, groupTypeLabel: context?.groupTypeLabel })

    const showComparison = !!compareFilter?.compare && insightData?.result?.length > 1
    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    return resultSeries ? (
        <div className="BoldNumber">
            <div
                className={clsx('BoldNumber__value', showPersonsModal ? 'cursor-pointer' : 'cursor-default')}
                onClick={
                    context?.onDataPointClick
                        ? () => context?.onDataPointClick?.({ compare: 'current' }, resultSeries)
                        : showPersonsModal && resultSeries.aggregated_value != null && !hasDataWarehouseSeries // != is intentional to catch undefined too
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
                }
                onMouseLeave={() => setIsTooltipShown(false)}
                ref={valueRef}
                onMouseEnter={() => setIsTooltipShown(true)}
            >
                <Textfit min={32} max={64}>
                    {formatAggregationAxisValue(trendsFilter, resultSeries.aggregated_value)}
                </Textfit>
            </div>
            {showComparison && <BoldNumberComparison showPersonsModal={showPersonsModal} context={context} />}
        </div>
    ) : (
        <InsightEmptyState />
    )
}

function BoldNumberComparison({
    showPersonsModal,
    context,
}: Pick<ChartParams, 'showPersonsModal' | 'context'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightData, querySource } = useValues(insightVizDataLogic(insightProps))

    if (!insightData?.result) {
        return null
    }

    const [currentPeriodSeries, previousPeriodSeries] = insightData.result as TrendResult[]

    const previousValue = previousPeriodSeries.aggregated_value
    const currentValue = currentPeriodSeries.aggregated_value

    const percentageDiff =
        previousValue === null || currentValue === null
            ? null
            : (currentValue - previousValue) / Math.abs(previousValue)

    const percentageDiffDisplay =
        percentageDiff === null
            ? 'No data for comparison in the'
            : percentageDiff > 0
            ? `Up ${percentage(percentageDiff)} from`
            : percentageDiff < 0
            ? `Down ${percentage(-percentageDiff)} from`
            : 'No change from'

    return (
        <LemonRow
            icon={
                percentageDiff === null ? (
                    <IconFlare />
                ) : percentageDiff > 0 ? (
                    <IconTrending />
                ) : percentageDiff < 0 ? (
                    <IconTrendingDown />
                ) : (
                    <IconTrendingFlat />
                )
            }
            className="BoldNumber__comparison"
            fullWidth
            center
        >
            <span>
                {percentageDiffDisplay}{' '}
                {currentValue === null ? (
                    'current period'
                ) : previousValue === null || !showPersonsModal ? (
                    'previous period'
                ) : (
                    <Link
                        onClick={() => {
                            if (context?.onDataPointClick) {
                                context.onDataPointClick({ compare: 'previous' }, currentPeriodSeries)
                            } else {
                                openPersonsModal({
                                    title: previousPeriodSeries.label,
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
                        }}
                    >
                        previous period
                    </Link>
                )}
            </span>
        </LemonRow>
    )
}

export function HogQLBoldNumber(): JSX.Element {
    const { response, responseLoading, tabularData } = useValues(dataVisualizationLogic)

    if (!response || responseLoading) {
        return (
            <div className="BoldNumber LemonTable HogQL">
                <div className="BoldNumber__value">
                    <Textfit min={32} max={120}>
                        Loading...
                    </Textfit>
                </div>
            </div>
        )
    }

    const formattedValue = tabularData?.[0]?.[0]?.formattedValue
    const directValue = response?.[0]?.[0]
    const resultsValue = 'results' in response ? response?.results?.[0]?.[0] : undefined
    const resultValue = 'result' in response ? response?.result?.[0]?.[0] : undefined

    // If any of the values is null, show empty state
    if (formattedValue === null || directValue === null || resultsValue === null || resultValue === null) {
        return (
            <div className="LemonTable HogQL">
                <InsightEmptyState />
            </div>
        )
    }

    const value = formattedValue ?? directValue ?? resultsValue ?? resultValue

    return (
        <div className="BoldNumber LemonTable HogQL">
            <div className="BoldNumber__value">
                <Textfit min={32} max={120}>
                    {String(value ?? 'Error')}
                </Textfit>
            </div>
        </div>
    )
}
