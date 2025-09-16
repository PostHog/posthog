import './FunnelBarVertical.scss'

import { useValues } from 'kea'
import { useLayoutEffect, useRef, useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams } from '~/types'

import { useFunnelTooltip } from '../FunnelTooltip'
import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { StepBarLabels } from './StepBarLabels'
import { StepBars } from './StepBars'
import { StepLegend } from './StepLegend'

interface FunnelBarVerticalCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

export function FunnelBarVertical({ showPersonsModal: showPersonsModalProp = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const vizRef = useFunnelTooltip(showPersonsModal)

    const { height: availableHeight } = useResizeObserver({ ref: vizRef })
    const [scrollbarHeightPx, setScrollbarHeightPx] = useState(0)
    const [stepLegendRowHeightPx, setStepLegendRowHeightPx] = useState(0)

    const seriesCount = visibleStepsWithConversionMetrics[0]?.nested_breakdown?.length ?? 0
    const barWidthPx =
        seriesCount >= 60
            ? 4
            : seriesCount >= 20
              ? 8
              : seriesCount >= 12
                ? 16
                : seriesCount >= 10
                  ? 20
                  : seriesCount >= 8
                    ? 24
                    : seriesCount >= 6
                      ? 32
                      : seriesCount >= 5
                        ? 40
                        : seriesCount >= 4
                          ? 48
                          : seriesCount >= 3
                            ? 64
                            : seriesCount >= 2
                              ? 96
                              : 192

    const scrollRef = useRef<HTMLDivElement | null>(null)
    const stepLegendRowRef = useRef<HTMLTableRowElement | null>(null)

    useLayoutEffect(() => {
        if (scrollRef.current) {
            setScrollbarHeightPx(scrollRef.current.offsetHeight - scrollRef.current.clientHeight)
        }
    }, [availableHeight])
    useLayoutEffect(() => {
        if (stepLegendRowRef.current) {
            setStepLegendRowHeightPx(stepLegendRowRef.current.clientHeight)
        }
    }, [availableHeight])

    /** Average conversion time is only shown if it's known for at least one step. */
    // != is intentional to catch undefined too
    const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)

    const minimumBarHeightPx = 150
    const borderHeightPx = 1

    // available height - border - legend - (maybe) scrollbar
    const barRowHeight = `max(${minimumBarHeightPx}px, calc(${availableHeight}px - ${borderHeightPx}px - ${stepLegendRowHeightPx}px - ${scrollbarHeightPx}px))`

    return (
        <div className="FunnelBarVertical" ref={vizRef} data-attr="funnel-bar-vertical">
            <ScrollableShadows scrollRef={scrollRef} direction="horizontal">
                <table
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={
                        {
                            '--bar-width': `${barWidthPx}px`,
                            '--bar-row-height': barRowHeight,
                        } as FunnelBarVerticalCSSProperties
                    }
                >
                    <colgroup>
                        {visibleStepsWithConversionMetrics.map((_, i) => (
                            <col key={i} width={0} />
                        ))}
                        <col width="100%" />
                        {/* The last column is meant to fill up leftover space. */}
                    </colgroup>
                    <tbody>
                        <tr>
                            <td>
                                <StepBarLabels />
                            </td>
                            {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                                <td key={stepIndex}>
                                    <StepBars step={step} stepIndex={stepIndex} showPersonsModal={showPersonsModal} />
                                </td>
                            ))}
                        </tr>
                        <tr ref={stepLegendRowRef}>
                            <td />
                            {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                                <td key={stepIndex}>
                                    <StepLegend
                                        step={step}
                                        stepIndex={stepIndex}
                                        showTime={showTime}
                                        showPersonsModal={showPersonsModal}
                                    />
                                </td>
                            ))}
                        </tr>
                    </tbody>
                </table>
            </ScrollableShadows>
        </div>
    )
}
