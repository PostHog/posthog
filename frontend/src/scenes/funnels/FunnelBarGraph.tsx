import React, { ForwardRefRenderFunction, useEffect, useRef, useState } from 'react'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, ButtonProps, Popover } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { useResizeObserver } from 'lib/utils/responsiveUtils'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { ArrowBottomRightOutlined } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useThrottledCallback } from 'use-debounce'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { InsightTooltip } from 'scenes/insights/InsightTooltip'
import { FunnelLayout } from 'lib/constants'
import {
    calcPercentage,
    getReferenceStep,
    humanizeOrder,
    getSeriesColor,
    getBreakdownMaxIndex,
    getSeriesPositionName,
    humanizeStepCount,
} from './funnelUtils'
import { ChartParams } from '~/types'

interface BarProps {
    percentage: number
    name?: string
    onBarClick?: () => void
    disabled?: boolean
    layout?: FunnelLayout
    isBreakdown?: boolean
    breakdownIndex?: number
    breakdownMaxIndex?: number
    breakdownSumPercentage?: number
    popoverTitle?: string | JSX.Element | null
    popoverMetrics?: { title: string; value: number | string; visible?: boolean }[]
}

type LabelPosition = 'inside' | 'outside'

function Bar({
    percentage,
    name,
    onBarClick,
    disabled,
    layout = FunnelLayout.horizontal,
    isBreakdown = false,
    breakdownIndex,
    breakdownMaxIndex,
    breakdownSumPercentage,
    popoverTitle = null,
    popoverMetrics = [],
}: BarProps): JSX.Element {
    const barRef = useRef<HTMLDivElement | null>(null)
    const labelRef = useRef<HTMLDivElement | null>(null)
    const [labelPosition, setLabelPosition] = useState<LabelPosition>('inside')
    const [labelVisible, setLabelVisible] = useState(true)
    const LABEL_POSITION_OFFSET = 8 // Defined here and in SCSS
    const { clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const cursorType = clickhouseFeaturesEnabled && !disabled ? 'pointer' : ''
    const hasBreakdownSum = isBreakdown && typeof breakdownSumPercentage === 'number'
    const shouldShowLabel = !isBreakdown || (hasBreakdownSum && labelVisible)

    function decideLabelPosition(): void {
        if (hasBreakdownSum) {
            // Label is always outside for breakdowns, but don't show if it doesn't fit in the wrapper
            setLabelPosition('outside')
            if (layout === FunnelLayout.horizontal) {
                const barWidth = barRef.current?.clientWidth ?? null
                const barOffset = barRef.current?.offsetLeft ?? null
                const wrapperWidth = barRef.current?.parentElement?.clientWidth ?? null
                const labelWidth = labelRef.current?.clientWidth ?? null
                if (barWidth !== null && barOffset !== null && wrapperWidth !== null && labelWidth !== null) {
                    if (wrapperWidth - (barWidth + barOffset) < labelWidth + LABEL_POSITION_OFFSET * 2) {
                        setLabelVisible(false)
                    } else {
                        setLabelVisible(true)
                    }
                }
            } else {
                const barOffset = barRef.current?.offsetTop ?? null
                const labelHeight = labelRef.current?.clientHeight ?? null
                if (barOffset !== null && labelHeight !== null) {
                    if (barOffset < labelHeight + LABEL_POSITION_OFFSET * 2) {
                        setLabelVisible(false)
                    } else {
                        setLabelVisible(true)
                    }
                }
            }
            return
        }
        // Place label inside or outside bar, based on whether it fits
        if (layout === FunnelLayout.horizontal) {
            const barWidth = barRef.current?.clientWidth ?? null
            const labelWidth = labelRef.current?.clientWidth ?? null
            if (barWidth !== null && labelWidth !== null) {
                if (labelWidth + LABEL_POSITION_OFFSET * 2 > barWidth) {
                    setLabelPosition('outside')
                    return
                }
            }
        } else {
            const barHeight = barRef.current?.clientHeight ?? null
            const labelHeight = labelRef.current?.clientHeight ?? null
            if (barHeight !== null && labelHeight !== null) {
                if (labelHeight + LABEL_POSITION_OFFSET * 2 > barHeight) {
                    setLabelPosition('outside')
                    return
                }
            }
        }
        setLabelPosition('inside')
    }

    useResizeObserver({
        callback: useThrottledCallback(decideLabelPosition, 200),
        element: barRef,
    })

    return (
        <Popover
            trigger="hover"
            placement="right"
            content={
                <InsightTooltip chartType="funnel" altTitle={popoverTitle}>
                    {popoverMetrics.map(({ title, value, visible }, index) =>
                        visible !== false ? <MetricRow key={index} title={title} value={value} /> : null
                    )}
                </InsightTooltip>
            }
        >
            <div
                ref={barRef}
                className={`funnel-bar ${getSeriesPositionName(breakdownIndex, breakdownMaxIndex)}`}
                style={{
                    flex: `${percentage} 100 0`,
                    cursor: cursorType,
                    backgroundColor: getSeriesColor(breakdownIndex),
                }}
                onClick={() => {
                    if (clickhouseFeaturesEnabled && !disabled && onBarClick) {
                        onBarClick()
                    }
                }}
            >
                {shouldShowLabel && (
                    <div
                        ref={labelRef}
                        className={`funnel-bar-percentage ${labelPosition}`}
                        title={name ? `Users who did ${name}` : undefined}
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={breakdownSumPercentage ?? percentage}
                    >
                        {humanizeNumber(breakdownSumPercentage ?? percentage, 2)}%
                    </div>
                )}
            </div>
        </Popover>
    )
}

interface ValueInspectorButtonProps {
    icon?: JSX.Element
    onClick: (e?: React.MouseEvent) => void
    children: React.ReactNode
    disabled?: boolean
    style?: React.CSSProperties
    title?: string | undefined
    innerRef?: React.MutableRefObject<HTMLElement | null>
}

export function ValueInspectorButton({
    icon,
    onClick,
    children,
    disabled = false,
    style,
    title,
    innerRef: refProp,
}: ValueInspectorButtonProps): JSX.Element {
    const props = {
        type: 'link' as const,
        icon,
        onClick,
        className: 'funnel-inspect-button',
        disabled,
        style,
        title,
        children: <span className="funnel-inspect-label">{children}</span>,
    }
    if (refProp) {
        const InnerComponent: ForwardRefRenderFunction<HTMLElement | null, ButtonProps> = (_, ref) => (
            <Button ref={ref} {...props} />
        )
        const RefComponent = React.forwardRef(InnerComponent)
        return <RefComponent ref={refProp} />
    } else {
        return <Button {...props} />
    }
}

interface AverageTimeInspectorProps {
    onClick: (e?: React.MouseEvent) => void
    disabled?: boolean
    averageTime: number
}

function AverageTimeInspector({ onClick, disabled, averageTime }: AverageTimeInspectorProps): JSX.Element {
    // Inspector button which automatically shows/hides the info text.
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const infoTextRef = useRef<HTMLDivElement | null>(null)
    const buttonRef = useRef<HTMLDivElement | null>(null)
    const [infoTextVisible, setInfoTextVisible] = useState(true)

    function decideTextVisible(): void {
        // Show/hide label position based on whether both items fit horizontally
        const wrapperWidth = wrapperRef.current?.clientWidth ?? null
        const infoTextWidth = infoTextRef.current?.offsetWidth ?? null
        const buttonWidth = buttonRef.current?.offsetWidth ?? null

        if (wrapperWidth !== null && infoTextWidth !== null && buttonWidth !== null) {
            if (infoTextWidth + buttonWidth <= wrapperWidth) {
                setInfoTextVisible(true)
                return
            }
        }
        setInfoTextVisible(false)
    }

    useEffect(() => {
        decideTextVisible()
    }, [])

    useResizeObserver({
        callback: useThrottledCallback(decideTextVisible, 200),
        element: wrapperRef,
    })

    return (
        <div ref={wrapperRef}>
            <span
                ref={infoTextRef}
                className="text-muted-alt"
                style={{ paddingRight: 4, display: 'inline-block', visibility: infoTextVisible ? undefined : 'hidden' }}
            >
                Average time:
            </span>
            <ValueInspectorButton
                innerRef={buttonRef}
                style={{ paddingLeft: 0, paddingRight: 0 }}
                onClick={onClick}
                disabled={disabled}
                title="Average of time elapsed for each user between completing this step and starting the next one."
            >
                {humanFriendlyDuration(averageTime, 2)}
            </ValueInspectorButton>
        </div>
    )
}

function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
    return (
        <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between' }}>
            <div>{title}</div>
            <div>
                <strong>{value}</strong>
            </div>
        </div>
    )
}

export function FunnelBarGraph({ filters, dashboardItemId, color = 'white' }: Omit<ChartParams, 'view'>): JSX.Element {
    const logic = funnelLogic({ dashboardItemId, filters })
    const {
        stepsWithConversionMetrics: steps,
        stepReference,
        barGraphLayout: layout,
        clickhouseFeaturesEnabled,
    } = useValues(logic)
    const { openPersonsModal } = useActions(funnelLogic)

    return (
        <div
            data-attr="funnel-bar-graph"
            className={`funnel-bar-graph ${layout}${color && color !== 'white' ? ' colored' : ''} ${color}`}
            style={dashboardItemId ? {} : { minHeight: 450 }}
        >
            {steps.map((step, i) => {
                const basisStep = getReferenceStep(steps, stepReference, i)
                const previousStep = getReferenceStep(steps, FunnelStepReference.previous, i)
                const showLineBefore = layout === FunnelLayout.horizontal && i > 0
                const showLineAfter = layout === FunnelLayout.vertical || i < steps.length - 1
                const breakdownMaxIndex = getBreakdownMaxIndex(
                    Array.isArray(step.nested_breakdown) ? step.nested_breakdown : undefined
                )
                const breakdownSum =
                    (Array.isArray(step.nested_breakdown) &&
                        step.nested_breakdown?.reduce((sum, item) => sum + item.count, 0)) ||
                    0
                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${showLineBefore ? 'before' : ''}`} />
                            <SeriesGlyph variant="funnel-step-glyph">{humanizeOrder(step.order)}</SeriesGlyph>
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div className="funnel-step-title">
                                <PropertyKeyInfo value={step.name} style={{ maxWidth: '100%' }} />
                            </div>
                            <div className={`funnel-step-metadata funnel-time-metadata ${layout}`}>
                                {step.average_conversion_time && step.average_conversion_time >= 0 + Number.EPSILON ? (
                                    <AverageTimeInspector
                                        onClick={() => {}}
                                        averageTime={step.average_conversion_time}
                                        disabled
                                    />
                                ) : null}
                            </div>
                        </header>
                        <div className="funnel-inner-viz">
                            <div className="funnel-bar-wrapper">
                                {Array.isArray(step.nested_breakdown) && step.nested_breakdown?.length ? (
                                    <>
                                        {step.nested_breakdown.map((breakdown, index) => {
                                            const barSizePercentage = calcPercentage(breakdown.count, basisStep.count)
                                            return (
                                                <Bar
                                                    key={`${breakdown.action_id}-${step.breakdown_value}-${index}`}
                                                    isBreakdown={true}
                                                    breakdownIndex={index}
                                                    breakdownMaxIndex={breakdownMaxIndex}
                                                    breakdownSumPercentage={
                                                        index === breakdownMaxIndex && breakdownSum
                                                            ? calcPercentage(breakdownSum, basisStep.count)
                                                            : undefined
                                                    }
                                                    percentage={barSizePercentage}
                                                    name={breakdown.name}
                                                    onBarClick={() =>
                                                        openPersonsModal(step, i + 1, breakdown.breakdown)
                                                    }
                                                    disabled={!!dashboardItemId}
                                                    layout={layout}
                                                    popoverTitle={
                                                        <div style={{ wordWrap: 'break-word' }}>
                                                            <PropertyKeyInfo value={step.name} />
                                                            {' • '}
                                                            {breakdown.breakdown || 'None'}
                                                        </div>
                                                    }
                                                    popoverMetrics={[
                                                        {
                                                            title: 'Completed step',
                                                            value: breakdown.count,
                                                        },
                                                        {
                                                            title: 'Conversion rate (total)',
                                                            value:
                                                                humanizeNumber(breakdown.conversionRates.total, 2) +
                                                                '%',
                                                        },
                                                        {
                                                            title: `Conversion rate (from step ${humanizeOrder(
                                                                previousStep.order
                                                            )})`,
                                                            value:
                                                                humanizeNumber(
                                                                    breakdown.conversionRates.fromPrevious,
                                                                    2
                                                                ) + '%',
                                                            visible: step.order !== 0,
                                                        },
                                                        {
                                                            title: 'Dropped off',
                                                            value: breakdown.droppedOffFromPrevious,
                                                            visible:
                                                                step.order !== 0 &&
                                                                breakdown.droppedOffFromPrevious > 0,
                                                        },
                                                        {
                                                            title: `Dropoff rate (from step ${humanizeOrder(
                                                                previousStep.order
                                                            )})`,
                                                            value:
                                                                humanizeNumber(
                                                                    100 - breakdown.conversionRates.fromPrevious,
                                                                    2
                                                                ) + '%',
                                                            visible:
                                                                step.order !== 0 &&
                                                                breakdown.droppedOffFromPrevious > 0,
                                                        },
                                                        {
                                                            title: 'Average time on step',
                                                            value: humanFriendlyDuration(
                                                                breakdown.average_conversion_time
                                                            ),
                                                            visible: !!breakdown.average_conversion_time,
                                                        },
                                                    ]}
                                                />
                                            )
                                        })}
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() =>
                                                clickhouseFeaturesEnabled &&
                                                !dashboardItemId &&
                                                openPersonsModal(step, -(i + 1))
                                            } // dropoff value for steps is negative
                                            style={{
                                                flex: `${100 - calcPercentage(breakdownSum, basisStep.count)} 100 0`,
                                                cursor: `${
                                                    clickhouseFeaturesEnabled && !dashboardItemId ? 'pointer' : ''
                                                }`,
                                            }}
                                        />
                                    </>
                                ) : (
                                    <>
                                        <Bar
                                            percentage={step.conversionRates.fromBasisStep}
                                            name={step.name}
                                            onBarClick={() => openPersonsModal(step, i + 1)}
                                            disabled={!!dashboardItemId}
                                            layout={layout}
                                            popoverTitle={<PropertyKeyInfo value={step.name} />}
                                            popoverMetrics={[
                                                {
                                                    title: 'Completed step',
                                                    value: step.count,
                                                },
                                                {
                                                    title: 'Conversion rate (total)',
                                                    value: humanizeNumber(step.conversionRates.total, 2) + '%',
                                                },
                                                {
                                                    title: `Conversion rate (from step ${humanizeOrder(
                                                        previousStep.order
                                                    )})`,
                                                    value: humanizeNumber(step.conversionRates.fromPrevious, 2) + '%',
                                                    visible: step.order !== 0,
                                                },
                                                {
                                                    title: 'Dropped off',
                                                    value: step.droppedOffFromPrevious,
                                                    visible: step.order !== 0 && step.droppedOffFromPrevious > 0,
                                                },
                                                {
                                                    title: `Dropoff rate (from step ${humanizeOrder(
                                                        previousStep.order
                                                    )})`,
                                                    value:
                                                        humanizeNumber(100 - step.conversionRates.fromPrevious, 2) +
                                                        '%',
                                                    visible: step.order !== 0 && step.droppedOffFromPrevious > 0,
                                                },
                                                {
                                                    title: 'Average time on step',
                                                    value: humanFriendlyDuration(step.average_conversion_time),
                                                    visible: !!step.average_conversion_time,
                                                },
                                            ]}
                                        />
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() =>
                                                clickhouseFeaturesEnabled &&
                                                !dashboardItemId &&
                                                openPersonsModal(step, -(i + 1))
                                            } // dropoff value for steps is negative
                                            style={{
                                                flex: `${100 - step.conversionRates.fromBasisStep} 100 0`,
                                                cursor: `${
                                                    clickhouseFeaturesEnabled && !dashboardItemId ? 'pointer' : ''
                                                }`,
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                            <div className="funnel-conversion-metadata funnel-step-metadata">
                                <div className="center-flex">
                                    <ValueInspectorButton
                                        onClick={() => openPersonsModal(step, i + 1)}
                                        disabled={!clickhouseFeaturesEnabled || !!dashboardItemId}
                                    >
                                        <span className="value-inspector-button-icon">
                                            <ArrowRightOutlined style={{ color: 'var(--success)' }} />
                                        </span>
                                        <b>{humanizeStepCount(step.count)}</b>
                                    </ValueInspectorButton>
                                    <span className="text-muted-alt">
                                        ({step.order > 0 ? calcPercentage(step.count, steps[i - 1].count) : '100'}
                                        %)
                                    </span>
                                </div>
                                <div
                                    className="text-muted-alt conversion-metadata-caption"
                                    style={layout === FunnelLayout.horizontal ? { flexGrow: 1 } : { marginBottom: 8 }}
                                >
                                    completed step
                                </div>
                                <div className="center-flex">
                                    <ValueInspectorButton
                                        onClick={() => openPersonsModal(step, -(i + 1))} // dropoff value from step 1 to 2 is -2, 2 to 3 is -3
                                        disabled={!clickhouseFeaturesEnabled || !!dashboardItemId}
                                        style={{ paddingRight: '0.25em' }}
                                    >
                                        <span
                                            className="value-inspector-button-icon"
                                            style={{
                                                padding: '4px 6px',
                                                marginRight: layout === FunnelLayout.horizontal ? 2 : 10,
                                            }} // This custom icon requires special handling
                                        >
                                            <ArrowBottomRightOutlined style={{ color: 'var(--danger)' }} />
                                        </span>
                                        <b>{humanizeStepCount(step.order > 0 ? steps[i - 1].count - step.count : 0)}</b>
                                    </ValueInspectorButton>
                                    <span className="text-muted-alt">
                                        (
                                        {step.order > 0
                                            ? Math.round((100 - calcPercentage(step.count, steps[i - 1].count)) * 100) /
                                              100
                                            : 0}
                                        %)
                                    </span>
                                </div>
                                <div className="text-muted-alt conversion-metadata-caption">dropped off</div>
                            </div>
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
