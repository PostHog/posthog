import { useValues } from 'kea'

import { LemonDropdown } from '@posthog/lemon-ui'

import { capitalizeFirstLetter, percentage } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Noun } from '~/models/groupsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics } from '~/types'

import { FunnelTooltip } from '../FunnelTooltip'
import { funnelDataLogic } from '../funnelDataLogic'
import { getSeriesPositionName } from '../funnelUtils'

interface BarProps {
    percentage: number
    name?: string
    onBarClick?: () => void
    disabled?: boolean
    isBreakdown?: boolean
    breakdownIndex?: number
    breakdownMaxIndex?: number
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
    step,
    stepIndex,
    breakdownFilter,
    aggregationTargetLabel,
}: BarProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { getFunnelsColor } = useValues(funnelDataLogic(insightProps))

    const cursorType = !disabled ? 'pointer' : ''

    // Labels are handled differently for breakdown vs non-breakdown funnels:
    // - Non-breakdown: Show labels on bars (CSS positions inside/outside based on width)
    // - Breakdown: Hide bar labels (CSS), summary shown in empty space instead
    const shouldShowLabel = !isBreakdown

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
                        aria-valuenow={conversionPercentage * 100}
                    >
                        {percentage(conversionPercentage, 1, true)}
                    </div>
                )}
            </div>
        </LemonDropdown>
    )
}
