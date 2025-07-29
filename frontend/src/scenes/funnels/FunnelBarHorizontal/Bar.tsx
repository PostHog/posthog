import { LemonDropdown } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { capitalizeFirstLetter, percentage } from 'lib/utils'
import { useRef, useState, useEffect } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Noun } from '~/models/groupsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { FunnelTooltip } from '../FunnelTooltip'
import { getSeriesPositionName } from '../funnelUtils'

interface BarProps {
    percentage: number
    name?: string
    onBarClick?: () => void
    disabled?: boolean
    isBreakdown?: boolean
    breakdownIndex?: number
    breakdownMaxIndex?: number
    breakdownSumPercentage?: number
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    breakdownFilter: BreakdownFilter | null | undefined
    aggregationTargetLabel: Noun
}

export function Bar({
    percentage: conversionPercentage,
    name,
    onBarClick,
    disabled,
    isBreakdown = false,
    breakdownIndex,
    breakdownMaxIndex,
    breakdownSumPercentage,
    step,
    stepIndex,
    breakdownFilter,
    aggregationTargetLabel,
}: BarProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { getFunnelsColor } = useValues(funnelDataLogic(insightProps))

    const barRef = useRef<HTMLDivElement | null>(null)
    const [labelVisible, setLabelVisible] = useState(true)
    const MINIMUM_SPACE_FOR_LABEL = 60 // pixels
    const cursorType = !disabled ? 'pointer' : ''
    const hasBreakdownSum = isBreakdown && typeof breakdownSumPercentage === 'number'
    const shouldShowLabel = (!isBreakdown || hasBreakdownSum) && labelVisible

    function checkLabelVisibility(): void {
        if (!hasBreakdownSum) {
            // For non-breakdowns, always show label
            setLabelVisible(true)
            return
        }

        const parentElement = barRef.current?.parentElement
        if (!parentElement) {
            return
        }

        const totalWidth = parentElement.clientWidth
        const usedPercentage = breakdownSumPercentage || 0
        const remainingWidth = totalWidth * (1 - usedPercentage)

        setLabelVisible(remainingWidth >= MINIMUM_SPACE_FOR_LABEL)
    }

    useEffect(() => {
        checkLabelVisibility()

        const parentElement = barRef.current?.parentElement
        if (!parentElement) {
            return
        }

        const resizeObserver = new ResizeObserver(() => {
            checkLabelVisibility()
        })

        resizeObserver.observe(parentElement)

        return () => {
            resizeObserver.disconnect()
        }
    }, [hasBreakdownSum, breakdownSumPercentage, checkLabelVisibility])

    if (!conversionPercentage) {
        return null
    }

    return (
        <LemonDropdown
            trigger="hover"
            placement="right"
            showArrow
            overlay={
                <FunnelTooltip
                    showPersonsModal={!disabled}
                    stepIndex={stepIndex}
                    series={step}
                    groupTypeLabel={aggregationTargetLabel.plural}
                    breakdownFilter={breakdownFilter}
                    embedded
                />
            }
        >
            <div
                ref={barRef}
                className={`funnel-bar ${getSeriesPositionName(breakdownIndex, breakdownMaxIndex)}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    flex: `${conversionPercentage} 1 0`,
                    cursor: cursorType,
                    backgroundColor: getFunnelsColor(step),
                }}
                onClick={() => {
                    if (!disabled && onBarClick) {
                        onBarClick()
                    }
                }}
            >
                {shouldShowLabel && (
                    <div
                        className="funnel-bar-percentage"
                        title={
                            name ? `${capitalizeFirstLetter(aggregationTargetLabel.plural)} who did ${name}` : undefined
                        }
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={(breakdownSumPercentage ?? conversionPercentage) * 100}
                    >
                        {percentage(breakdownSumPercentage ?? conversionPercentage, 1, true)}
                    </div>
                )}
            </div>
        </LemonDropdown>
    )
}
