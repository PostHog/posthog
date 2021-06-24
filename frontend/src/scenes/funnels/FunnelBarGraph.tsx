import React, { useEffect, useRef, useState } from 'react'
import { humanizeNumber, pluralize } from 'lib/utils'
import { FunnelStep } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button } from 'antd'

import './FunnelBarGraph.scss'
import { ClockCircleOutlined, UserOutlined } from '@ant-design/icons'

interface FunnelBarGraphProps {
    layout?: 'horizontal' | 'vertical'
    steps: FunnelStep[]
}

interface BarProps {
    order: number
    percentage: number
    name?: string
}

type LabelPosition = 'inside' | 'outside'

function Bar({ percentage, order, name }: BarProps): JSX.Element {
    console.log(order)
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

    const resizeObserver = new ResizeObserver((entries: ResizeObserverEntry[]) => {
        entries.forEach(() => decideLabelPosition())
    })

    useEffect(() => {
        if (barRef.current) {
            resizeObserver.observe(barRef.current)
        }
        decideLabelPosition()
    }, [])

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

    return layout === 'horizontal' ? (
        <div>
            {steps.map((step) => (
                <section key={step.order} className="funnel-step">
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
                            <ValueInspectorButton icon={<UserOutlined />} onClick={() => {}}>
                                {step.count} completed
                            </ValueInspectorButton>
                        </div>
                    </header>
                    <Bar order={step.order} percentage={(step.count / referenceStep.count) * 100} name={step.name} />
                </section>
            ))}
        </div>
    ) : (
        <>{null}</>
    )
}
