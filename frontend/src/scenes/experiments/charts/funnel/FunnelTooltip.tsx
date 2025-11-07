import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { IconHandClick } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelStepWithConversionMetrics } from '~/types'

const FUNNEL_TOOLTIP_OFFSET_PX = 4

export interface FunnelTooltipData {
    stepIndex: number
    series: FunnelStepWithConversionMetrics
}

interface FunnelTooltipProps {
    stepIndex: number
    series: FunnelStepWithConversionMetrics
    embedded?: boolean
    hasSessionData?: boolean
}

function FunnelTooltipContent({
    stepIndex,
    series,
    embedded = false,
    hasSessionData = false,
}: FunnelTooltipProps): JSX.Element {
    return (
        <div
            className={clsx('FunnelTooltip InsightTooltip', {
                'p-2': !embedded,
                'border-none': embedded,
                'shadow-none': embedded,
            })}
        >
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />} fullWidth>
                <strong>
                    <EntityFilterInfo filter={getActionFilterFromFunnelStep(series)} allowWrap />
                    {series.breakdown_value && (
                        <>
                            <span className="mx-1">•</span>
                            {formatBreakdownLabel(series.breakdown_value, null, [], (value) => value?.toString() || '')}
                        </>
                    )}
                </strong>
            </LemonRow>
            <LemonDivider className="my-2" />
            <table>
                <tbody>
                    <tr>
                        <td>{stepIndex === 0 ? 'Entered' : 'Converted'}</td>
                        <td>{humanFriendlyNumber(series.count)}</td>
                    </tr>
                    {stepIndex > 0 && (
                        <tr>
                            <td>Dropped off</td>
                            <td>{humanFriendlyNumber(series.droppedOffFromPrevious || 0)}</td>
                        </tr>
                    )}
                    <tr>
                        <td>Conversion so far</td>
                        <td>{percentage(series.conversionRates.total || 0, 2, true)}</td>
                    </tr>
                    {stepIndex > 0 && (
                        <tr>
                            <td>Conversion from previous</td>
                            <td>{percentage(series.conversionRates.fromPrevious || 0, 2, true)}</td>
                        </tr>
                    )}
                    {stepIndex > 0 && series.median_conversion_time != null && (
                        <tr>
                            <td>Median time from previous</td>
                            <td>{humanFriendlyDuration(series.median_conversion_time, { maxUnits: 3 })}</td>
                        </tr>
                    )}
                    {stepIndex > 0 && series.average_conversion_time != null && (
                        <tr>
                            <td>Average time from previous</td>
                            <td>{humanFriendlyDuration(series.average_conversion_time, { maxUnits: 3 })}</td>
                        </tr>
                    )}
                </tbody>
            </table>
            {hasSessionData && (
                <div className="table-subtext table-subtext-click-to-inspect">
                    <IconHandClick className="mr-1 mb-0.5" />
                    Click to view persons
                </div>
            )}
        </div>
    )
}

export function useFunnelTooltip(): {
    vizRef: React.RefObject<HTMLDivElement>
    showTooltip: (
        rect: [number, number, number],
        stepIndex: number,
        series: FunnelStepWithConversionMetrics,
        hasSessionData?: boolean
    ) => void
    hideTooltip: () => void
} {
    const vizRef = useRef<HTMLDivElement>(null)
    const { getTooltip } = useInsightTooltip()

    const [isTooltipShown, setIsTooltipShown] = useState(false)
    const [currentTooltip, setCurrentTooltip] = useState<FunnelTooltipData | null>(null)
    const [tooltipOrigin, setTooltipOrigin] = useState<[number, number, number] | null>(null)
    const [hasSessionData, setHasSessionData] = useState(false)

    const showTooltip = (
        rect: [number, number, number],
        stepIndex: number,
        series: FunnelStepWithConversionMetrics,
        hasSessionData: boolean = false
    ): void => {
        setIsTooltipShown(true)
        setCurrentTooltip({ stepIndex, series })
        setTooltipOrigin(rect)
        setHasSessionData(hasSessionData)
    }

    const hideTooltip = (): void => {
        setIsTooltipShown(false)
        setCurrentTooltip(null)
        setTooltipOrigin(null)
    }

    useEffect(() => {
        const svgRect = vizRef.current?.getBoundingClientRect()
        const [tooltipRoot, tooltipEl] = getTooltip()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()

        if (tooltipOrigin && currentTooltip) {
            tooltipRoot.render(
                <FunnelTooltipContent
                    stepIndex={currentTooltip.stepIndex}
                    series={currentTooltip.series}
                    hasSessionData={hasSessionData}
                />
            )

            // Put the tooltip to the bottom right of the cursor, but flip to left if tooltip doesn't fit
            let xOffset: number
            if (
                svgRect &&
                tooltipRect &&
                tooltipOrigin[0] + tooltipOrigin[2] + tooltipRect.width + FUNNEL_TOOLTIP_OFFSET_PX >
                    svgRect.x + svgRect.width
            ) {
                xOffset = -tooltipRect.width - FUNNEL_TOOLTIP_OFFSET_PX
            } else {
                xOffset = tooltipOrigin[2] + FUNNEL_TOOLTIP_OFFSET_PX
            }
            tooltipEl.style.left = `${window.pageXOffset + tooltipOrigin[0] + xOffset}px`
            tooltipEl.style.top = `${window.pageYOffset + tooltipOrigin[1]}px`
        } else {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
        }
    }, [isTooltipShown, tooltipOrigin, currentTooltip]) // eslint-disable-line react-hooks/exhaustive-deps

    return { vizRef, showTooltip, hideTooltip }
}
