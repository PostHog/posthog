import { LemonDropdown } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { capitalizeFirstLetter, percentage } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
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
    /** Bar wrapper width in px. */
    wrapperWidth: number
}
type LabelPosition = 'inside' | 'outside'

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
    wrapperWidth,
}: BarProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { getFunnelsColor } = useValues(funnelDataLogic(insightProps))

    const barRef = useRef<HTMLDivElement | null>(null)
    const labelRef = useRef<HTMLDivElement | null>(null)
    const [labelPosition, setLabelPosition] = useState<LabelPosition>('inside')
    const [labelVisible, setLabelVisible] = useState(true)
    const LABEL_POSITION_OFFSET = 8 // Defined here and in SCSS
    const cursorType = !disabled ? 'pointer' : ''
    const hasBreakdownSum = isBreakdown && typeof breakdownSumPercentage === 'number'
    const shouldShowLabel = !isBreakdown || (hasBreakdownSum && labelVisible)

    function decideLabelPosition(): void {
        if (hasBreakdownSum) {
            // Label is always outside for breakdowns, but don't show if it doesn't fit in the wrapper
            setLabelPosition('outside')
            const barWidth = barRef.current?.clientWidth ?? null
            const barOffset = barRef.current?.offsetLeft ?? null
            const labelWidth = labelRef.current?.clientWidth ?? null
            if (barWidth !== null && barOffset !== null && wrapperWidth !== null && labelWidth !== null) {
                if (wrapperWidth - (barWidth + barOffset) < labelWidth + LABEL_POSITION_OFFSET * 2) {
                    setLabelVisible(false)
                } else {
                    setLabelVisible(true)
                }
            }
            return
        }
        // Place label inside or outside bar, based on whether it fits
        const barWidth = barRef.current?.clientWidth ?? null
        const labelWidth = labelRef.current?.clientWidth ?? null
        if (barWidth !== null && labelWidth !== null) {
            if (labelWidth + LABEL_POSITION_OFFSET * 2 > barWidth) {
                setLabelPosition('outside')
                return
            }
        }
        setLabelPosition('inside')
    }

    useEffect(() => {
        decideLabelPosition()
    }, [wrapperWidth])

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
                        ref={labelRef}
                        className={`funnel-bar-percentage ${labelPosition}`}
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
