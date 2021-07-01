import React, { useRef, useState } from 'react'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { FunnelStep } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, Tooltip } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { useResizeObserver } from 'lib/utils/responsiveUtils'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'

import './FunnelBarGraph.scss'
import { ArrowBottomRightOutlined } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useValues } from 'kea'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'

function calcPercentage(numerator: number, denominator: number): number {
    return (numerator / denominator) * 100 || 0
}

function humanizeOrder(order: number): number {
    return order + 1
}
interface FunnelBarGraphProps {
    layout?: 'horizontal' | 'vertical'
    steps: FunnelStep[]
}

interface BarProps {
    percentage: number
    name?: string
}

type LabelPosition = 'inside' | 'outside'

function Bar({ percentage, name }: BarProps): JSX.Element {
    const barRef = useRef<HTMLDivElement | null>(null)
    const labelRef = useRef<HTMLDivElement | null>(null)
    const [labelPosition, setLabelPosition] = useState<LabelPosition>('inside')
    const LABEL_POSITION_OFFSET = 8 // Defined here and in SCSS

    function decideLabelPosition(): void {
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
        callback: decideLabelPosition,
        element: barRef,
    })

    return (
        <div className="funnel-bar-wrapper">
            <div ref={barRef} className="funnel-bar" style={{ width: `${percentage}%` }}>
                <div
                    ref={labelRef}
                    className={`funnel-bar-percentage ${labelPosition}`}
                    title={name ? `Users who did ${name}` : undefined}
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={percentage}
                >
                    {humanizeNumber(percentage, 2)}%
                </div>
            </div>
        </div>
    )
}

interface ValueInspectorButtonProps {
    icon?: JSX.Element
    onClick: (e?: React.SyntheticEvent) => any
    children: React.ReactNode
    disabled?: boolean
    style?: React.CSSProperties
}

function ValueInspectorButton({
    icon,
    onClick,
    children,
    disabled = false,
    style,
}: ValueInspectorButtonProps): JSX.Element {
    return (
        <Button
            type="link"
            icon={icon}
            onClick={onClick}
            className="funnel-inspect-button"
            disabled={disabled}
            style={style}
        >
            <span className="funnel-inspect-label">{children}</span>
        </Button>
    )
}

function getReferenceStep(steps: FunnelStep[], stepReference: FunnelStepReference, index?: number): FunnelStep {
    // Step to serve as denominator of percentage calculations.
    // step[0] is full-funnel conversion, previous is relative.
    if (!index || index <= 0) {
        return steps[0]
    }
    switch (stepReference) {
        case FunnelStepReference.previous:
            return steps[index - 1]
        case FunnelStepReference.total:
        default:
            return steps[0]
    }
}

export function FunnelBarGraph({ layout = 'horizontal', steps: stepsParam }: FunnelBarGraphProps): JSX.Element {
    const { stepReference } = useValues(funnelLogic)
    const steps = [...stepsParam].sort((a, b) => a.order - b.order)

    return layout === 'horizontal' ? (
        <div>
            {steps.map((step, i) => {
                const basisStep = getReferenceStep(steps, stepReference, i)
                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${i > 0 ? 'before' : ''}`} />
                            <SeriesGlyph style={{ backgroundColor: '#fff', zIndex: 2 }}>
                                {humanizeOrder(step.order)}
                            </SeriesGlyph>
                            <div className={`funnel-series-linebox ${steps[i + 1] ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div className="funnel-step-title">
                                <PropertyKeyInfo value={step.name} />
                            </div>
                            <div className="funnel-step-metadata">
                                {step.average_time >= 0 + Number.EPSILON ? (
                                    <Tooltip title="Average time spent on this step before continuing to the next.">
                                        Average time:{' '}
                                        <ValueInspectorButton
                                            onClick={() => {}}
                                            style={{ paddingLeft: 0, paddingRight: 0 }}
                                            disabled
                                        >
                                            {humanFriendlyDuration(step.average_time)}
                                        </ValueInspectorButton>
                                    </Tooltip>
                                ) : null}
                            </div>
                        </header>
                        <Bar percentage={calcPercentage(step.count, basisStep.count)} name={step.name} />
                        <footer>
                            <div className="funnel-step-metadata">
                                <ValueInspectorButton
                                    icon={<ArrowRightOutlined style={{ color: 'var(--success)' }} />}
                                    onClick={() => {}}
                                    disabled
                                >
                                    {step.count} completed
                                </ValueInspectorButton>
                                {i > 0 && step.order > 0 && steps[i - 1]?.count > step.count && (
                                    <span>
                                        <ValueInspectorButton
                                            icon={<ArrowBottomRightOutlined style={{ color: 'var(--danger)' }} />}
                                            onClick={() => {}}
                                            disabled
                                            style={{ paddingRight: '0.25em' }}
                                        >
                                            {steps[i - 1].count - step.count} dropped off
                                        </ValueInspectorButton>
                                        <span style={{ color: 'var(--primary-alt)' }}>
                                            ({humanizeNumber(100 - calcPercentage(step.count, steps[i - 1].count), 2)}%
                                            from previous step)
                                        </span>
                                    </span>
                                )}
                            </div>
                        </footer>
                    </section>
                )
            })}
        </div>
    ) : (
        <>{null}</>
    )
}
