import { useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { Textfit } from 'react-textfit'
import clsx from 'clsx'

import { insightLogic } from '../../insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartParams, TrendResult } from '~/types'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { ensureTooltipElement } from '../LineGraph/LineGraph'
import { groupsModel } from '~/models/groupsModel'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { IconFlare, IconTrendingDown, IconTrendingFlat, IconTrendingUp } from 'lib/lemon-ui/icons'
import { LemonRow } from '@posthog/lemon-ui'
import { percentage } from 'lib/utils'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import './BoldNumber.scss'

/** The tooltip is offset by a few pixels from the cursor to give it some breathing room. */
const BOLD_NUMBER_TOOLTIP_OFFSET_PX = 8

function useBoldNumberTooltip({
    showPersonsModal,
    isTooltipShown,
}: {
    showPersonsModal: boolean
    isTooltipShown: boolean
}): React.RefObject<HTMLDivElement> {
    const { insightProps } = useValues(insightLogic)
    const { series, insightData, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const divRef = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        const divRect = divRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'

        const seriesResult = insightData?.result?.[0]

        ReactDOM.render(
            <InsightTooltip
                renderCount={(value: number) => <>{formatAggregationAxisValue(trendsFilter, value)}</>}
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
                groupTypeLabel={aggregationLabel(series?.[0].math_group_type_index).plural}
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
    const { insightProps } = useValues(insightLogic)
    const { insightData, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const [textFitTimer, setTextFitTimer] = useState<NodeJS.Timeout | null>(null)

    const [isTooltipShown, setIsTooltipShown] = useState(false)
    const valueRef = useBoldNumberTooltip({ showPersonsModal, isTooltipShown })

    const showComparison = !!trendsFilter?.compare && insightData?.result?.length > 1
    const resultSeries = insightData?.result?.[0] as TrendResult | undefined

    useEffect(() => {
        // sometimes text fit can get stuck and leave text too small
        // force a resize after a small delay
        const timer = setTimeout(() => window.dispatchEvent(new CustomEvent('resize')), 300)
        setTextFitTimer(timer)
        return () => clearTimeout(timer)
    }, [])

    return resultSeries ? (
        <div className="BoldNumber">
            <Textfit
                mode="single"
                min={32}
                max={120}
                onReady={() => {
                    // if fontsize has calculated then no need for a resize event
                    if (textFitTimer) {
                        clearTimeout(textFitTimer)
                    }
                }}
                style={{ lineHeight: 1 }}
            >
                <div
                    className={clsx('BoldNumber__value', showPersonsModal ? 'cursor-pointer' : 'cursor-default')}
                    onClick={
                        // != is intentional to catch undefined too
                        showPersonsModal && resultSeries.aggregated_value != null
                            ? () => {
                                  if (resultSeries.persons?.url) {
                                      openPersonsModal({
                                          url: resultSeries.persons?.url,
                                          title: <PropertyKeyInfo value={resultSeries.label} disablePopover />,
                                      })
                                  }
                              }
                            : undefined
                    }
                    onMouseLeave={() => setIsTooltipShown(false)}
                    ref={valueRef}
                    onMouseEnter={() => setIsTooltipShown(true)}
                >
                    {formatAggregationAxisValue(trendsFilter, resultSeries.aggregated_value)}
                </div>
            </Textfit>
            {showComparison && <BoldNumberComparison showPersonsModal={showPersonsModal} />}
        </div>
    ) : (
        <InsightEmptyState />
    )
}

function BoldNumberComparison({ showPersonsModal }: Pick<ChartParams, 'showPersonsModal'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightData } = useValues(insightVizDataLogic(insightProps))

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
                    <IconTrendingUp />
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
                    <a
                        onClick={() => {
                            if (previousPeriodSeries.persons?.url) {
                                openPersonsModal({
                                    url: previousPeriodSeries.persons?.url,
                                    title: <PropertyKeyInfo value={previousPeriodSeries.label} disablePopover />,
                                })
                            }
                        }}
                    >
                        previous period
                    </a>
                )}
            </span>
        </LemonRow>
    )
}
