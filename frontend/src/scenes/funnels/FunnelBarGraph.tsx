import React, { ForwardRefRenderFunction, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { capitalizeFirstLetter, humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, ButtonProps, Popover } from 'antd'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { IconTrendingFlatDown, IconInfinity, IconTrendingFlat, IconInfo } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useThrottledCallback } from 'use-debounce'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { LEGACY_InsightTooltip } from 'scenes/insights/InsightTooltip/LEGACY_InsightTooltip'
import { FunnelLayout } from 'lib/constants'
import { getBreakdownMaxIndex, getReferenceStep, getSeriesPositionName } from './funnelUtils'
import { ChartParams, FunnelStepReference, StepOrderValue } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { useResizeObserver } from '../../lib/hooks/useResizeObserver'
import { getSeriesColor } from 'lib/colors'
import { FunnelStepMore } from './FunnelStepMore'

interface BarProps {
    percentage: number
    name?: string
    onBarClick?: () => void
    disabled?: boolean
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
        <Tooltip
            title={
                <>
                    <b>This is a repeated event in a sequence</b>
                    <p>
                        When an event is repeated across funnel steps, it is interpreted as a sequence. For example, a
                        three-step funnel consisting of pageview events is interpretted as first pageview, followed by
                        second pageview, followed by a third pageview.
                    </p>
                </>
            }
        >
            <IconInfo style={{ marginLeft: '0.375rem', fontSize: '1.25rem', color: 'var(--muted-alt)' }} />
        </Tooltip>
    )
}

function Bar({
    percentage: conversionPercentage,
    name,
    onBarClick,
    disabled,
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
    const cursorType = !disabled ? 'pointer' : ''
    const hasBreakdownSum = isBreakdown && typeof breakdownSumPercentage === 'number'
    const shouldShowLabel = !isBreakdown || (hasBreakdownSum && labelVisible)

    function decideLabelPosition(): void {
        if (hasBreakdownSum) {
            // Label is always outside for breakdowns, but don't show if it doesn't fit in the wrapper
            setLabelPosition('outside')
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

    useResizeObserver({
        onResize: useThrottledCallback(decideLabelPosition, 200),
        ref: barRef,
    })

    return (
        <Popover
            trigger="hover"
            placement="right"
            content={
                <LEGACY_InsightTooltip altTitle={popoverTitle}>
                    {popoverMetrics.map(({ title, value, visible }, index) =>
                        visible !== false ? <MetricRow key={index} title={title} value={value} /> : null
                    )}
                </LEGACY_InsightTooltip>
            }
        >
            <div
                ref={barRef}
                className={`funnel-bar ${getSeriesPositionName(breakdownIndex, breakdownMaxIndex)}`}
                style={{
                    flex: `${conversionPercentage} 1 0`,
                    cursor: cursorType,
                    backgroundColor: getSeriesColor(breakdownIndex ?? 0),
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

export function FunnelBarGraph(props: ChartParams): JSX.Element {
    const {
        filters,
        visibleStepsWithConversionMetrics: steps,
        stepReference,
        aggregationTargetLabel,
        isModalActive,
    } = useValues(funnelLogic)
    const { openPersonsModalForStep } = useActions(funnelLogic)

    // Everything rendered after is a funnel in top-to-bottom mode.
    return (
        <div data-attr="funnel-bar-graph" className={clsx('funnel-bar-graph', 'white')}>
            {steps.map((step, stepIndex) => {
                const basisStep = getReferenceStep(steps, stepReference, stepIndex)
                const previousStep = getReferenceStep(steps, FunnelStepReference.previous, stepIndex)
                const showLineBefore = stepIndex > 0
                const showLineAfter = stepIndex < steps.length - 1
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
                                <SeriesGlyph variant="funnel-step-glyph">{step.order + 1}</SeriesGlyph>
                            )}
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div style={{ display: 'flex', alignItems: 'center', maxWidth: '100%', flexGrow: 1 }}>
                                <div className="funnel-step-title">
                                    {filters.funnel_order_type === StepOrderValue.UNORDERED ? (
                                        <span>Completed {step.order + 1} steps</span>
                                    ) : (
                                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                    )}
                                </div>
                                {filters.funnel_order_type !== StepOrderValue.UNORDERED &&
                                    stepIndex > 0 &&
                                    step.action_id === steps[stepIndex - 1].action_id && <DuplicateStepIndicator />}
                                <FunnelStepMore stepIndex={stepIndex} />
                            </div>
                            <div className={`funnel-step-metadata funnel-time-metadata ${FunnelLayout.horizontal}`}>
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
                                                            value: percentage(breakdown.conversionRates.total, 1, true),
                                                        },
                                                        {
                                                            title: `Conversion rate (from step ${
                                                                previousStep.order + 1
                                                            })`,
                                                            value: percentage(
                                                                breakdown.conversionRates.fromPrevious,
                                                                1,
                                                                true
                                                            ),
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
                                                            title: `Dropoff rate (from step ${previousStep.order + 1})`,
                                                            value: percentage(
                                                                1 - breakdown.conversionRates.fromPrevious,
                                                                1,
                                                                true
                                                            ),
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
                                                cursor: `${!props.inCardView ? 'pointer' : ''}`,
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
                                                    value: percentage(step.conversionRates.total, 1, true),
                                                },
                                                {
                                                    title: `Conversion rate (from step ${previousStep.order + 1})`,
                                                    value: percentage(step.conversionRates.fromPrevious, 1, true),
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
                                                    title: `Dropoff rate (from step ${previousStep.order + 1})`,
                                                    value: percentage(1 - step.conversionRates.fromPrevious, 1, true),
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
                                                cursor: `${!props.inCardView ? 'pointer' : ''}`,
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                            <div className="funnel-conversion-metadata funnel-step-metadata">
                                <div className="step-stat">
                                    <div className="center-flex">
                                        <ValueInspectorButton
                                            onClick={() => openPersonsModalForStep({ step, converted: true })}
                                            disabled={!isModalActive}
                                        >
                                            <IconTrendingFlat
                                                style={{ color: 'var(--success)' }}
                                                className="value-inspector-button-icon"
                                            />
                                            <b>
                                                {pluralize(
                                                    step.count,
                                                    aggregationTargetLabel.singular,
                                                    aggregationTargetLabel.plural
                                                )}
                                            </b>
                                        </ValueInspectorButton>
                                        <span className="text-muted-alt">
                                            (
                                            {percentage(
                                                step.order > 0 ? step.count / steps[stepIndex - 1].count : 1,
                                                1,
                                                true
                                            )}
                                            )
                                        </span>
                                    </div>
                                    <div className="text-muted-alt conversion-metadata-caption" style={{ flexGrow: 1 }}>
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
                                            <IconTrendingFlatDown
                                                style={{ color: 'var(--danger)' }}
                                                className="value-inspector-button-icon"
                                            />
                                            <b>
                                                {pluralize(
                                                    dropOffCount,
                                                    aggregationTargetLabel.singular,
                                                    aggregationTargetLabel.plural
                                                )}
                                            </b>
                                        </ValueInspectorButton>
                                        <span className="text-muted-alt">
                                            (
                                            {percentage(
                                                step.order > 0 ? 1 - step.count / steps[stepIndex - 1].count : 0,
                                                1,
                                                true
                                            )}
                                            )
                                        </span>
                                    </div>
                                    <div className="text-muted-alt conversion-metadata-caption">dropped off</div>
                                </div>
                            </div>
                        </div>
                    </section>
                )
            })}
        </div>
    )
}
