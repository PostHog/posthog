import React, { ForwardRefRenderFunction, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { capitalizeFirstLetter, humanFriendlyDuration, pluralize } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, ButtonProps, Popover } from 'antd'
import { ArrowRightOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { ArrowBottomRightOutlined, IconInfinity } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useThrottledCallback } from 'use-debounce'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import {
    formatDisplayPercentage,
    getBreakdownMaxIndex,
    getReferenceStep,
    getSeriesColor,
    getSeriesPositionName,
    humanizeOrder,
    humanizeStepCount,
} from './funnelUtils'
import { FunnelStepReference, StepOrderValue } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepTable } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { FunnelStepDropdown } from './FunnelStepDropdown'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useResizeObserver } from '../../lib/hooks/useResizeObserver'

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
    aggregationTargetLabel: { singular: string; plural: string }
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
    aggregationTargetLabel,
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
        onResize: useThrottledCallback(decideLabelPosition, 200),
        ref: barRef,
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
                        title={
                            name ? `${capitalizeFirstLetter(aggregationTargetLabel.plural)} who did ${name}` : undefined
                        }
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
    aggregationTargetLabel: { singular: string; plural: string }
}

function AverageTimeInspector({
    onClick,
    disabled,
    averageTime,
    aggregationTargetLabel,
}: AverageTimeInspectorProps): JSX.Element {
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
        onResize: useThrottledCallback(decideTextVisible, 200),
        ref: wrapperRef,
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
                title={`Average of time elapsed for each ${aggregationTargetLabel.singular} between completing this step and starting the next one.`}
            >
                {humanFriendlyDuration(averageTime, 2)}
            </ValueInspectorButton>
        </div>
    )
}

export function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
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
        aggregationTargetLabel,
        isModalActive,
    } = useValues(logic)
    const { openPersonsModalForStep } = useActions(logic)
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

                const dropOffCount = step.order > 0 ? steps[stepIndex - 1].count - step.count : 0

                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${showLineBefore ? 'before' : ''}`} />
                            {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                <SeriesGlyph variant="funnel-step-glyph">
                                    <IconInfinity style={{ fill: 'var(--primary_alt)', width: 14 }} />
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
                                    ) : (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
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
                                        aggregationTargetLabel={aggregationTargetLabel}
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
                                                        openPersonsModalForStep({
                                                            step,
                                                            converted: true,
                                                        })
                                                    }
                                                    disabled={!isModalActive}
                                                    layout={layout}
                                                    popoverTitle={
                                                        <div style={{ wordWrap: 'break-word' }}>
                                                            <PropertyKeyInfo value={step.name} />
                                                            {' • '}
                                                            {(Array.isArray(breakdown.breakdown)
                                                                ? breakdown.breakdown.join(', ')
                                                                : breakdown.breakdown) || 'Other'}
                                                        </div>
                                                    }
                                                    popoverMetrics={[
                                                        {
                                                            title: 'Completed step',
                                                            value: pluralize(
                                                                breakdown.count,
                                                                aggregationTargetLabel.singular,
                                                                aggregationTargetLabel.plural
                                                            ),
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
                                                            value: pluralize(
                                                                breakdown.droppedOffFromPrevious,
                                                                aggregationTargetLabel.singular,
                                                                aggregationTargetLabel.plural
                                                            ),
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
                                                    aggregationTargetLabel={aggregationTargetLabel}
                                                />
                                            )
                                        })}
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() => openPersonsModalForStep({ step, converted: false })} // dropoff value for steps is negative
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
                                            onBarClick={() => openPersonsModalForStep({ step, converted: true })}
                                            disabled={!isModalActive}
                                            layout={layout}
                                            popoverTitle={<PropertyKeyInfo value={step.name} />}
                                            popoverMetrics={[
                                                {
                                                    title: 'Completed step',
                                                    value: pluralize(
                                                        step.count,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural
                                                    ),
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
                                                    value: pluralize(
                                                        step.droppedOffFromPrevious,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural
                                                    ),
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
                                            aggregationTargetLabel={aggregationTargetLabel}
                                        />
                                        <div
                                            className="funnel-bar-empty-space"
                                            onClick={() => openPersonsModalForStep({ step, converted: false })} // dropoff value for steps is negative
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
                                                onClick={() => openPersonsModalForStep({ step, converted: true })}
                                                disabled={!isModalActive}
                                            >
                                                <span className="value-inspector-button-icon">
                                                    <ArrowRightOutlined style={{ color: 'var(--success)' }} />
                                                </span>
                                                <b>
                                                    {humanizeStepCount(step.count)}{' '}
                                                    {pluralize(
                                                        step.count,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural,
                                                        false
                                                    )}
                                                </b>
                                            </ValueInspectorButton>
                                            <span className="text-muted-alt">
                                                (
                                                {formatDisplayPercentage(
                                                    step.order > 0 ? step.count / steps[stepIndex - 1].count : 1
                                                )}
                                                %)
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
                                                onClick={() => openPersonsModalForStep({ step, converted: false })}
                                                disabled={!isModalActive}
                                            >
                                                <span className="value-inspector-button-icon">
                                                    <ArrowBottomRightOutlined style={{ color: 'var(--danger)' }} />
                                                </span>
                                                <b>
                                                    {humanizeStepCount(dropOffCount)}{' '}
                                                    {pluralize(
                                                        dropOffCount,
                                                        aggregationTargetLabel.singular,
                                                        aggregationTargetLabel.plural,
                                                        false
                                                    )}
                                                </b>
                                            </ValueInspectorButton>
                                            <span className="text-muted-alt">
                                                (
                                                {formatDisplayPercentage(
                                                    step.order > 0 ? 1 - step.count / steps[stepIndex - 1].count : 0
                                                )}
                                                %)
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
