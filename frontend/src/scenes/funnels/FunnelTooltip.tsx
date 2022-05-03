import { getContext, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { funnelLogic } from './funnelLogic'
import {  FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ensureTooltipElement } from 'scenes/insights/LineGraph/LineGraph'
import { Provider } from 'react-redux'
import { LemonDivider } from 'lib/components/LemonDivider'

/** The tooltip is offset horizontally by a few pixels from the bar to give it some breathing room. */
const FUNNEL_TOOLTIP_OFFSET_PX = 2

interface FunnelTooltipProps {
    stepIndex: number
    series: FunnelStepWithConversionMetrics
}

function FunnelTooltip({ stepIndex, series}: FunnelTooltipProps): JSX.Element {
    return (
        <div className="FunnelBarChartTooltip">
            <LemonRow
                icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                fullWidth
            >
                <strong>
                    <EntityFilterInfo
                        filter={getActionFilterFromFunnelStep(series)}
                        style={{ display: 'inline-block' }}
                    />{' '}
                    • {series.breakdown_value}
                </strong>
            </LemonRow>
            <LemonDivider style={{ marginTop: '0.125rem' }} />
            <table>
                <tbody>
                    <tr>
                        <td>{stepIndex === 0 ? 'Entered' : 'Converted'}</td>
                        <td>{humanFriendlyNumber(series.count)}</td>
                    </tr>
                    {stepIndex > 0 && (
                        <tr>
                            <td>Dropped off</td>
                            <td>{humanFriendlyNumber(series.droppedOffFromPrevious)}</td>
                        </tr>
                    )}
                    <tr>
                        <td>Conversion so far</td>
                        <td>{percentage(series.conversionRates.total, 1, true)}</td>
                    </tr>
                    {stepIndex > 0 && (
                        <tr>
                            <td>Conversion from previous</td>
                            <td>
                                {percentage(series.conversionRates.fromPrevious, 1, true)}
                            </td>
                        </tr>
                    )}
                    {stepIndex > 0 && series.average_conversion_time != null && (
                        <tr>
                            <td>Average time from previous</td>
                            <td>
                                {humanFriendlyDuration(series.average_conversion_time, 3)}
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>)
}

export function useFunnelTooltip(): React.RefObject<HTMLDivElement> {
    const { isTooltipShown, currentTooltip, tooltipCoordinates } = useValues(funnelLogic)

    const vizRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const svgRect = vizRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (tooltipCoordinates) {
            ReactDOM.render(
                <Provider store={getContext().store}>
                    {currentTooltip && (
                        <FunnelTooltip
                            stepIndex={currentTooltip[0]}
                            series={currentTooltip[1]}
                        />
                    )}
                </Provider>,
                tooltipEl
            )
            // Put the tooltip to the bottom right of the cursor, but flip to left if tooltip doesn't fit
            let xOffset: number
            if (
                svgRect &&
                tooltipRect &&
                tooltipCoordinates[0] + tooltipRect.width + FUNNEL_TOOLTIP_OFFSET_PX > svgRect.x + svgRect.width
            ) {
                xOffset = -(tooltipRect.width + FUNNEL_TOOLTIP_OFFSET_PX)
            } else {
                xOffset = FUNNEL_TOOLTIP_OFFSET_PX
            }
            tooltipEl.style.left = `${window.pageXOffset + tooltipCoordinates[0] + xOffset}px`
            tooltipEl.style.top = `${window.pageYOffset + tooltipCoordinates[1]}px`
        } else {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
        }
    }, [isTooltipShown, tooltipCoordinates, currentTooltip])

    return vizRef
}
