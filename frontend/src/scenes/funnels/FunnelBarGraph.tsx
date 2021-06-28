import React, { useRef, useState } from 'react'
import { humanizeNumber, pluralize } from 'lib/utils'
import { FunnelStep } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button } from 'antd'
import { ClockCircleOutlined, UserOutlined } from '@ant-design/icons'
import { useResizeObserver } from 'lib/utils/responsiveUtils'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'

import './FunnelBarGraph.scss'

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
                    aria-role="progressbar"
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
}

function ValueInspectorButton({ icon, onClick, children, disabled = false }: ValueInspectorButtonProps): JSX.Element {
    return (
        <Button type="link" icon={icon} onClick={onClick} className="funnel-inspect-button" disabled={disabled}>
            <span className="funnel-inspect-label">{children}</span>
        </Button>
    )
}

export function FunnelBarGraph({ layout = 'horizontal', steps: stepsParam }: FunnelBarGraphProps): JSX.Element {
    const steps = stepsParam.sort((a, b) => a.order - b.order)
    const referenceStep = steps[0] // Compare values to first step, i.e. total

    function calcPercentage(numerator: number, denominator: number): number {
        return (numerator / denominator) * 100 || 0
    }

    function humanizeOrder(order: number): number {
        return order + 1
    }

    return layout === 'horizontal' ? (
        <div>
            {steps.map((step, i) => (
                <section key={step.order} className="funnel-step">
                    <div className="funnel-series-container">
                        <div className={`funnel-series-linebox ${steps[i - 1] ? 'before' : ''}`} />
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
                            {step.average_time >= 0 + Number.EPSILON && step.order !== 0 ? (
                                <ValueInspectorButton icon={<ClockCircleOutlined />} onClick={() => {}} disabled>
                                    {pluralize(step.average_time, 'hour')}
                                </ValueInspectorButton>
                            ) : null}
                            <ValueInspectorButton icon={<UserOutlined />} onClick={() => {}} disabled /* TODO */>
                                {step.count} completed
                            </ValueInspectorButton>
                        </div>
                    </header>
                    <Bar percentage={calcPercentage(step.count, referenceStep.count)} name={step.name} />
                    {step.order !== 0 && steps[i - 1]?.count > step.count && (
                        <footer>
                            <div className="funnel-step-metadata">
                                <ValueInspectorButton icon={<UserOutlined /> /* TODO */} onClick={() => {}} disabled>
                                    {steps[i - 1].count - step.count} dropped off
                                </ValueInspectorButton>
                                <span>
                                    ({100 - calcPercentage(step.count, steps[i - 1].count)}% from previous step)
                                </span>
                            </div>
                        </footer>
                    )}
                </section>
            ))}
        </div>
    ) : (
        <>{null}</>
    )
}
