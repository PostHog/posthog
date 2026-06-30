// .FunnelTooltip styles live in FunnelBarVertical.scss; import here so they load on the quill funnel
// charts that reuse this tooltip (the old FunnelBarVertical that used to pull them in is gone).
import './FunnelBarVertical/FunnelBarVertical.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ClickToInspectActors } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'
import { funnelTooltipLogic } from './funnelTooltipLogic'
import { funnelComparePeriodDateRange, funnelTooltipHeaderLabel, hasBreakdown } from './funnelUtils'

/** The tooltip is offset horizontally by a few pixels from the bar to give it some breathing room. */
const FUNNEL_TOOLTIP_OFFSET_PX = 4

export interface FunnelTooltipProps {
    showPersonsModal: boolean
    stepIndex: number
    series: FunnelStepWithConversionMetrics
    groupTypeLabel: string
    breakdownFilter: BreakdownFilter | null | undefined
    embedded?: boolean
    /** Date range of the hovered series' compare period; shown when the series is compare-tagged. */
    comparePeriodDateRange?: string | null
    /** Baseline conversion rate across all breakdown values; shown only for breakdown variants past the first step. */
    aggregateConversionRate?: number | null
}

export function FunnelTooltip({
    showPersonsModal,
    stepIndex,
    series,
    groupTypeLabel,
    breakdownFilter,
    embedded = false,
    comparePeriodDateRange,
    aggregateConversionRate,
}: FunnelTooltipProps): JSX.Element {
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    return (
        <div
            data-attr="funnel-tooltip"
            className={clsx('FunnelTooltip InsightTooltip', {
                'p-2': !embedded,
                'border-none': embedded,
                'shadow-none': embedded,
            })}
        >
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />} fullWidth>
                <strong>
                    <EntityFilterInfo filter={getActionFilterFromFunnelStep(series)} allowWrap />
                    <span className="mx-1">•</span>
                    {funnelTooltipHeaderLabel({
                        // Pure compare bars (no real breakdown) show only the period; breakdown and
                        // breakdown + compare bars show the breakdown value (plus the period if any).
                        breakdownLabel:
                            !series.compare_label || hasBreakdown(series.breakdown_value)
                                ? formatBreakdownLabel(
                                      series.breakdown_value,
                                      breakdownFilter,
                                      allCohorts.results,
                                      formatPropertyValueForDisplay
                                  )
                                : null,
                        compareLabel: series.compare_label,
                        comparePeriodDateRange,
                    })}
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
                            <td>{humanFriendlyNumber(series.droppedOffFromPrevious)}</td>
                        </tr>
                    )}
                    <tr>
                        <td>Conversion so far</td>
                        <td>{percentage(series.conversionRates.total, 2, true)}</td>
                    </tr>
                    {stepIndex > 0 && aggregateConversionRate != null && (
                        <tr>
                            <td>Baseline conversion rate</td>
                            <td>{percentage(aggregateConversionRate, 2, true)}</td>
                        </tr>
                    )}
                    {stepIndex > 0 && (
                        <tr>
                            <td>Conversion from previous</td>
                            <td>{percentage(series.conversionRates.fromPrevious, 2, true)}</td>
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
            {showPersonsModal && (
                <>
                    <LemonDivider className="my-2" />
                    <ClickToInspectActors groupTypeLabel={groupTypeLabel} />
                </>
            )}
        </div>
    )
}

export function useFunnelTooltip(showPersonsModal: boolean): React.RefObject<HTMLDivElement> {
    const { insightProps } = useValues(insightLogic)
    const { breakdownFilter, querySource, insightData } = useValues(funnelDataLogic(insightProps))
    const { isTooltipShown, currentTooltip, tooltipOrigin } = useValues(funnelTooltipLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const vizRef = useRef<HTMLDivElement>(null)
    const { getTooltip } = useInsightTooltip()

    useEffect(() => {
        const svgRect = vizRef.current?.getBoundingClientRect()
        const [tooltipRoot, tooltipEl] = getTooltip()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (tooltipOrigin) {
            tooltipRoot.render(
                <>
                    {currentTooltip && (
                        <FunnelTooltip
                            showPersonsModal={showPersonsModal}
                            stepIndex={currentTooltip[0]}
                            series={currentTooltip[1]}
                            groupTypeLabel={aggregationLabel(querySource?.aggregation_group_type_index).plural}
                            breakdownFilter={breakdownFilter}
                            comparePeriodDateRange={
                                currentTooltip[1].compare_label
                                    ? funnelComparePeriodDateRange(
                                          currentTooltip[1].compare_label,
                                          insightData?.resolved_date_range,
                                          querySource?.compareFilter?.compare_to
                                      )
                                    : null
                            }
                        />
                    )}
                </>
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
    }, [isTooltipShown, tooltipOrigin, currentTooltip]) // oxlint-disable-line react-hooks/exhaustive-deps

    return vizRef
}
