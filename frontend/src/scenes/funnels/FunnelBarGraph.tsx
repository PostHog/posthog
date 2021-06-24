import React from 'react'
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

function Bar({ percentage, order, name }: BarProps): JSX.Element {
    console.log(order)
    return (
        <div className="funnel-bar-wrapper">
            <div className="funnel-bar" style={{ width: `${percentage}%` }}>
                <div
                    className="funnel-bar-percentage"
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
                        <div>
                            {' '}
                            {/* div wrapper for flex purposes */}
                            <PropertyKeyInfo value={step.name} />
                        </div>
                        <div className="funnel-step-metadata">
                            {step.average_time >= 0 && step.order !== 0 ? (
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
