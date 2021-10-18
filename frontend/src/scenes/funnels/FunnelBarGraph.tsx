import React, { ForwardRefRenderFunction, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import useSize from '@react-hook/size'
import { compactNumber, humanFriendlyDuration } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, ButtonProps, Popover } from 'antd'
import { ArrowRightOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useResizeObserver } from 'lib/utils/responsiveUtils'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { ArrowBottomRightOutlined, Infinity } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useThrottledCallback } from 'use-debounce'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import {
    cleanBreakdownValue,
    formatDisplayPercentage,
    getBreakdownMaxIndex,
    getReferenceStep,
    getSeriesColor,
    getSeriesPositionName,
    humanizeOrder,
    humanizeStepCount,
} from './funnelUtils'
import { StepOrderValue, FunnelStepWithConversionMetrics, FunnelStepReference } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepTable } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { FunnelStepDropdown } from './FunnelStepDropdown'
import { insightLogic } from 'scenes/insights/insightLogic'

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

function DuplicateStepIndicator(): JSX.Element {
    return (
        <span style={{ marginLeft: 4 }}>
            <Tooltip
                title={
                    <>
                        <b>Sequential &amp; Repeated Events</b>
                        <p>
                            When an event is repeated across funnel steps, it is interpreted as a sequence. For example,
                            a three-step funnel consisting of pageview events is interpretted as first pageview,
                            followed by second pageview, followed by a third pageview.
                        </p>
                    </>
                }
            >
                <InfoCircleOutlined className="info-indicator" />
            </Tooltip>
        </span>
    )
}

interface BreakdownBarGroupProps {
    currentStep: FunnelStepWithConversionMetrics
    basisStep: FunnelStepWithConversionMetrics
    previousStep: FunnelStepWithConversionMetrics
    showLabels: boolean
    onBarClick?: (breakdown_value: string | undefined | number) => void
    isClickable: boolean
    isSingleSeries?: boolean
}

export function BreakdownVerticalBarGroup({
    currentStep,
    basisStep,
    previousStep,
    showLabels,
    onBarClick,
    isClickable,
    isSingleSeries = false,
}: BreakdownBarGroupProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const [, height] = useSize(ref)
    const barWidth = `calc(${100 / (currentStep?.nested_breakdown?.length ?? 1)}% - 2px)`

    return (
        <div className="breakdown-bar-group" ref={ref}>
            {currentStep?.nested_breakdown?.map((breakdown, breakdownIndex) => {
                const basisBreakdownCount = basisStep?.nested_breakdown?.[breakdownIndex]?.count ?? 1
                const currentBarHeight = (height * breakdown.count) / basisBreakdownCount
                const previousBarHeight =
                    (height * (previousStep?.nested_breakdown?.[breakdownIndex]?.count ?? 0)) / basisBreakdownCount
                const color = getSeriesColor(breakdown.order, isSingleSeries)

                const popoverMetrics = [
                    {
                        title: 'Completed step',
                        value: breakdown.count,
                    },
                    {
                        title: 'Conversion rate (total)',
                        value: formatDisplayPercentage(breakdown.conversionRates.total) + '%',
                    },
                    {
                        title: `Conversion rate (from step ${humanizeOrder(previousStep.order)})`,
                        value: formatDisplayPercentage(breakdown.conversionRates.fromPrevious) + '%',
                        visible: currentStep.order !== 0,
                    },
                    {
                        title: 'Dropped off',
                        value: breakdown.droppedOffFromPrevious,
                        visible: currentStep.order !== 0 && breakdown.droppedOffFromPrevious > 0,
                    },
                    {
                        title: `Dropoff rate (from step ${humanizeOrder(previousStep.order)})`,
                        value: formatDisplayPercentage(1 - breakdown.conversionRates.fromPrevious) + '%',
                        visible: currentStep.order !== 0 && breakdown.droppedOffFromPrevious > 0,
                    },
                    {
                        title: 'Average time on step',
                        value: humanFriendlyDuration(breakdown.average_conversion_time),
                        visible: !!breakdown.average_conversion_time,
                    },
                ]

                return (
                    <div
                        key={breakdownIndex}
                        className="breakdown-bar-column"
                        style={{
                            width: barWidth,
                        }}
                    >
                        {currentStep.order > 0 && (
                            <div
                                className="breakdown-previous-bar"
                                style={{
                                    height: previousBarHeight,
                                    backgroundColor: color,
                                    width: barWidth,
                                }}
                            />
                        )}
                        <Popover
                            trigger="hover"
                            placement="right"
                            content={
                                <InsightTooltip
                                    altTitle={
                                        <div style={{ wordWrap: 'break-word' }}>
                                            <PropertyKeyInfo value={currentStep.name} />
                                            {(breakdown.breakdown_value === 'Baseline'
                                                ? ''
                                                : ` • ${breakdown.breakdown}`) ?? ' • Other'}
                                        </div>
                                    }
                                >
                                    {popoverMetrics.map(({ title, value, visible }, index) =>
                                        visible !== false ? <MetricRow key={index} title={title} value={value} /> : null
                                    )}
                                </InsightTooltip>
                            }
                        >
                            <div
                                className="breakdown-current-bar"
                                style={{
                                    height: currentBarHeight,
                                    backgroundColor: color,
                                    width: barWidth,
                                    cursor: isClickable ? 'pointer' : undefined,
                                }}
                                onClick={() => onBarClick && onBarClick(cleanBreakdownValue(breakdown.breakdown_value))}
                            />
                        </Popover>
                        {showLabels && (
                            <div
                                className="breakdown-label"
                                style={{
                                    bottom: currentBarHeight + 4,
                                    width: barWidth,
                                }}
                            >
                                {breakdown.count > 0 ? compactNumber(breakdown.count) : ''}
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

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
    const { insightProps } = useValues(insightLogic)
    const { clickhouseFeaturesEnabled } = useValues(funnelLogic(insightProps))
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
                <InsightTooltip altTitle={popoverTitle}>
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
                    flex: `${percentage} 1 0`,
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
                        aria-valuenow={(breakdownSumPercentage ?? percentage) * 100}
                    >
                        {formatDisplayPercentage(breakdownSumPercentage ?? percentage)}%
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
                <strong style={{ paddingLeft: 6 }}>{value}</strong>
            </div>
        </div>
    )
}

export function FunnelBarGraph({ color = 'white' }: { color?: string }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { dashboardItemId } = insightProps
    const logic = funnelLogic(insightProps)
    const {
        filters,
        visibleStepsWithConversionMetrics: steps,
        stepReference,
        barGraphLayout: layout,
        clickhouseFeaturesEnabled,
    } = useValues(logic)
    const { openPersonsModal } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    // If the layout is vertical, we render bars using the table as a legend. See FunnelStepTable

    if (featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] && layout === FunnelLayout.vertical) {
        return <FunnelStepTable />
    }

    return (
        <div
            data-attr="funnel-bar-graph"
            className={`funnel-bar-graph ${layout}${color && color !== 'white' ? ' colored' : ''} ${color}`}
            style={insightProps.syncWithUrl ? { minHeight: 450 } : {}}
        >
            {steps.map((step, stepIndex) => {
                const basisStep = getReferenceStep(steps, stepReference, stepIndex)
                const previousStep = getReferenceStep(steps, FunnelStepReference.previous, stepIndex)
                const showLineBefore = layout === FunnelLayout.horizontal && stepIndex > 0
                const showLineAfter = layout === FunnelLayout.vertical || stepIndex < steps.length - 1
                const breakdownMaxIndex = getBreakdownMaxIndex(
                    Array.isArray(step.nested_breakdown) ? step.nested_breakdown : undefined
                )
                const breakdownSum =
                    (Array.isArray(step.nested_breakdown) &&
                        step.nested_breakdown?.reduce((sum, item) => sum + item.count, 0)) ||
                    0

                const isBreakdown =
                    Array.isArray(step.nested_breakdown) &&
                    step.nested_breakdown?.length !== undefined &&
                    !(step.nested_breakdown.length === 1 && step.nested_breakdown[0].breakdown_value === 'Baseline')

                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${showLineBefore ? 'before' : ''}`} />
                            {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                <SeriesGlyph variant="funnel-step-glyph">
                                    <Infinity style={{ fill: 'var(--primary_alt)', width: 14 }} />
                                </SeriesGlyph>
                            ) : (
                                <SeriesGlyph variant="funnel-step-glyph">{humanizeOrder(step.order)}</SeriesGlyph>
                            )}
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div style={{ display: 'flex', maxWidth: '100%', flexGrow: 1 }}>
                                <div className="funnel-step-title">
                                    {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                        <span>Completed {humanizeOrder(step.order)} steps</span>
                                    ) : featureFlags[FEATURE_FLAGS.RENAME_FILTERS] ? (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                    ) : (
                                        <PropertyKeyInfo value={step.name} style={{ maxWidth: '100%' }} />
                                    )}
                                </div>
                                {clickhouseFeaturesEnabled &&
                                    filters.funnel_order_type !== StepOrderValue.UNORDERED &&
                                    stepIndex > 0 &&
                                    step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                <FunnelStepDropdown index={stepIndex} />
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
                            <div className={clsx('funnel-bar-wrapper', { breakdown: isBreakdown })}>
                                {isBreakdown ? (
                                    <>
                                        {step?.nested_breakdown?.map((breakdown, index) => {
                                            const barSizePercentage = breakdown.count / basisStep.count
                                            return (
                                                <Bar
                                                    key={`${breakdown.action_id}-${step.breakdown_value}-${index}`}
                                                    isBreakdown={true}
                                                    breakdownIndex={index}
                                                    breakdownMaxIndex={breakdownMaxIndex}
                                                    breakdownSumPercentage={
                                                        index === breakdownMaxIndex && breakdownSum
                                                            ? breakdownSum / basisStep.count
                                                            : undefined
                                                    }
                                                    percentage={barSizePercentage}
                                                    name={breakdown.name}
                                                    onBarClick={() =>
                                                        openPersonsModal(
                                                            step,
                                                            stepIndex + 1,
                                                            cleanBreakdownValue(breakdown.breakdown_value)
                                                        )
                                                    }
                                                    disabled={!!dashboardItemId}
                                                    layout={layout}
                                                    popoverTitle={
                                                        <div style={{ wordWrap: 'break-word' }}>
                                                            <PropertyKeyInfo value={step.name} />
                                                            {' • '}
                                                            {breakdown.breakdown || 'Other'}
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
                                                                formatDisplayPercentage(
                                                                    breakdown.conversionRates.total
                                                                ) + '%',
                                                        },
                                                        {
                                                            title: `Conversion rate (from step ${humanizeOrder(
                                                                previousStep.order
                                                            )})`,
                                                            value:
                                                                formatDisplayPercentage(
                                                                    breakdown.conversionRates.fromPrevious
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
                                                                formatDisplayPercentage(
                                                                    1 - breakdown.conversionRates.fromPrevious
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
                                                openPersonsModal(step, -(stepIndex + 1))
                                            } // dropoff value for steps is negative
                                            style={{
                                                flex: `${1 - breakdownSum / basisStep.count} 1 0`,
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
                                            onBarClick={() => openPersonsModal(step, stepIndex + 1)}
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
                                                    value: formatDisplayPercentage(step.conversionRates.total) + '%',
                                                },
                                                {
                                                    title: `Conversion rate (from step ${humanizeOrder(
                                                        previousStep.order
                                                    )})`,
                                                    value:
                                                        formatDisplayPercentage(step.conversionRates.fromPrevious) +
                                                        '%',
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
                                                        formatDisplayPercentage(1 - step.conversionRates.fromPrevious) +
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
                                                openPersonsModal(step, -(stepIndex + 1))
                                            } // dropoff value for steps is negative
                                            style={{
                                                flex: `${1 - step.conversionRates.fromBasisStep} 1 0`,
                                                cursor: `${
                                                    clickhouseFeaturesEnabled && !dashboardItemId ? 'pointer' : ''
                                                }`,
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                            {(!featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] ||
                                layout === FunnelLayout.horizontal) && (
                                <div className="funnel-conversion-metadata funnel-step-metadata">
                                    <div className="step-stat">
                                        <div className="center-flex">
                                            <ValueInspectorButton
                                                onClick={() => openPersonsModal(step, stepIndex + 1)}
                                                disabled={!clickhouseFeaturesEnabled || !!dashboardItemId}
                                            >
                                                <span className="value-inspector-button-icon">
                                                    <ArrowRightOutlined style={{ color: 'var(--success)' }} />
                                                </span>
                                                <b>{humanizeStepCount(step.count)}</b>
                                            </ValueInspectorButton>
                                            <span className="text-muted-alt">
                                                (
                                                {formatDisplayPercentage(
                                                    step.order > 0 ? step.count / steps[stepIndex - 1].count : 1
                                                )}
                                                % )
                                            </span>
                                        </div>
                                        <div
                                            className="text-muted-alt conversion-metadata-caption"
                                            style={
                                                layout === FunnelLayout.horizontal
                                                    ? { flexGrow: 1 }
                                                    : { marginBottom: 8 }
                                            }
                                        >
                                            completed step
                                        </div>
                                    </div>
                                    <div
                                        className="step-stat"
                                        style={stepIndex === 0 ? { visibility: 'hidden' } : undefined}
                                    >
                                        <div className="center-flex">
                                            <ValueInspectorButton
                                                onClick={() => openPersonsModal(step, -(stepIndex + 1))} // dropoff value from step 1 to 2 is -2, 2 to 3 is -3
                                                disabled={!clickhouseFeaturesEnabled || !!dashboardItemId}
                                            >
                                                <span className="value-inspector-button-icon">
                                                    <ArrowBottomRightOutlined style={{ color: 'var(--danger)' }} />
                                                </span>
                                                <b>
                                                    {humanizeStepCount(
                                                        step.order > 0 ? steps[stepIndex - 1].count - step.count : 0
                                                    )}
                                                </b>
                                            </ValueInspectorButton>
                                            <span className="text-muted-alt">
                                                (
                                                {formatDisplayPercentage(
                                                    step.order > 0 ? 1 - step.count / steps[stepIndex - 1].count : 0
                                                )}
                                                % )
                                            </span>
                                        </div>
                                        <div className="text-muted-alt conversion-metadata-caption">dropped off</div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
