import { useValues } from 'kea'
import React, { useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { funnelLogic } from './funnelLogic'
import { FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ensureTooltipElement } from 'scenes/insights/LineGraph/LineGraph'
import { LemonDivider } from 'lib/components/LemonDivider'
import { cohortsModel } from '~/models/cohortsModel'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTable'
import { ClickToInspectActors } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { groupsModel } from '~/models/groupsModel'

/** The tooltip is offset horizontally by a few pixels from the bar to give it some breathing room. */
const FUNNEL_TOOLTIP_OFFSET_PX = 2

interface FunnelTooltipProps {
    showPersonsModal: boolean
    stepIndex: number
    series: FunnelStepWithConversionMetrics
    groupTypeLabel: string
}

function FunnelTooltip({ showPersonsModal, stepIndex, series, groupTypeLabel }: FunnelTooltipProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)

    return (
        <div className="FunnelTooltip">
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />} fullWidth>
                <strong>
                    <EntityFilterInfo
                        filter={getActionFilterFromFunnelStep(series)}
                        style={{ display: 'inline-block' }}
                    />{' '}
                    • {formatBreakdownLabel(cohorts, series.breakdown_value)}
                </strong>
            </LemonRow>
            <LemonDivider style={{ marginTop: '0.25rem' }} />
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
                            <td>{percentage(series.conversionRates.fromPrevious, 1, true)}</td>
                        </tr>
                    )}
                    {stepIndex > 0 && series.median_conversion_time != null && (
                        <tr>
                            <td>Median time from previous</td>
                            <td>{humanFriendlyDuration(series.median_conversion_time, 3)}</td>
                        </tr>
                    )}
                    {stepIndex > 0 && series.average_conversion_time != null && (
                        <tr>
                            <td>Average time from previous</td>
                            <td>{humanFriendlyDuration(series.average_conversion_time, 3)}</td>
                        </tr>
                    )}
                </tbody>
            </table>
            {showPersonsModal && <ClickToInspectActors groupTypeLabel={groupTypeLabel} />}
        </div>
    )
}

export function useFunnelTooltip(showPersonsModal: boolean): React.RefObject<HTMLDivElement> {
    const { filters, isTooltipShown, currentTooltip, tooltipOrigin } = useValues(funnelLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const vizRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const svgRect = vizRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (tooltipOrigin) {
            ReactDOM.render(
                <>
                    {currentTooltip && (
                        <FunnelTooltip
                            showPersonsModal={showPersonsModal}
                            stepIndex={currentTooltip[0]}
                            series={currentTooltip[1]}
                            groupTypeLabel={aggregationLabel(filters.aggregation_group_type_index).plural}
                        />
                    )}
                </>,
                tooltipEl
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
    }, [isTooltipShown, tooltipOrigin, currentTooltip])

    return vizRef
}
