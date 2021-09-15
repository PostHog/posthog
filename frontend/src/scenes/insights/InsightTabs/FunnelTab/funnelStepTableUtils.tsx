import { FlattenedFunnelStep, FlattenedFunnelStepByBreakdown, FunnelStepWithConversionMetrics } from '~/types'
import { getReferenceStep, getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { RenderedCell } from 'rc-table/lib/interface'
import React from 'react'
import { BreakdownVerticalBarGroup } from 'scenes/funnels/FunnelBarGraph'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { zeroPad } from 'lib/utils'

export function getColor(step: FlattenedFunnelStep, fallbackColor: string, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order) || fallbackColor
}

export function getStepColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getColor(step, 'var(--text-default)', isBreakdown)
}

export function isBreakdownChildType(
    stepBreakdown: FlattenedFunnelStep['breakdown']
): stepBreakdown is string | number | undefined {
    return ['string', 'number', 'undefined'].includes(typeof stepBreakdown)
}

export const renderSubColumnTitle = (title: string): JSX.Element => <span className="sub-column-title">{title}</span>

export const renderColumnTitle = (title: string): JSX.Element => <span className="column-title">{title}</span>

export const EmptyValue = <span className="text-muted-alt">-</span>

function BreakdownBarGroupWrapper({
    step,
    dashboardItemId,
}: {
    step: FunnelStepWithConversionMetrics
    dashboardItemId?: number
}): JSX.Element {
    const logic = funnelLogic({ dashboardItemId })
    const { stepReference, visibleStepsWithConversionMetrics: steps } = useValues(logic)
    const basisStep = getReferenceStep(steps, stepReference, step.order)
    const previousStep = getReferenceStep(steps, FunnelStepReference.previous, step.order)

    return (
        <div className="funnel-bar-wrapper breakdown vertical">
            <BreakdownVerticalBarGroup currentStep={step} basisStep={basisStep} previousStep={previousStep} />
            <div className="funnel-bar-empty-space" />
            <div className="funnel-bar-axis">
                <div className="axis-tick-line" />
                <div className="axis-tick-line" />
                <div className="axis-tick-line" />
                <div className="axis-tick-line" />
                <div className="axis-tick-line" />
                <div className="axis-tick-line" />
            </div>
        </div>
    )
}

export const renderGraphAndHeader = (
    rowIndex: number,
    colIndex: number,
    defaultElement: JSX.Element,
    headerElement: JSX.Element,
    step?: FunnelStepWithConversionMetrics,
    dashboardItemId?: number
): JSX.Element | RenderedCell<FlattenedFunnelStepByBreakdown> => {
    if (rowIndex === 0 || rowIndex === 1) {
        // Empty cell
        if (colIndex === 0) {
            if (rowIndex === 0) {
                return {
                    props: {
                        colSpan: 3,
                        className: 'dividing-column no-border-bottom',
                    },
                }
            }
            return {
                children: (
                    <div className="funnel-bar-wrapper breakdown vertical axis-wrapper">
                        <div className="axis">
                            <div className="axis-tick">100%</div>
                            <div className="axis-tick">80%</div>
                            <div className="axis-tick">60%</div>
                            <div className="axis-tick">40%</div>
                            <div className="axis-tick">20%</div>
                            <div className="axis-tick">0%</div>
                        </div>
                        <div className="funnel-bar-axis label">
                            <div className="axis-tick-line" />
                            <div className="axis-tick-line" />
                            <div className="axis-tick-line" />
                            <div className="axis-tick-line" />
                            <div className="axis-tick-line" />
                            <div className="axis-tick-line" />
                        </div>
                    </div>
                ),
                props: {
                    colSpan: 3,
                    className: 'dividing-column axis-labels-column',
                },
            }
        }
        // First base step
        if (colIndex === 3) {
            if (rowIndex === 0) {
                return {
                    children: (
                        <div className="funnel-step-title">
                            <span className="funnel-step-glyph">{zeroPad(humanizeOrder(step?.order ?? 0), 2)}</span>
                            <PropertyKeyInfo value={step?.name ?? ''} disableIcon className="funnel-step-name" />
                        </div>
                    ),
                    props: {
                        colSpan: 2,
                        className: 'dividing-column funnel-step-title-row',
                    },
                }
            }
            return {
                children: (
                    <BreakdownBarGroupWrapper
                        dashboardItemId={dashboardItemId}
                        step={step as FunnelStepWithConversionMetrics}
                    />
                ),
                props: {
                    colSpan: 2,
                    className: 'dividing-column',
                },
            }
        }
        if (colIndex < 5) {
            return {
                props: {
                    colSpan: 0,
                },
            }
        }
        // Subsequent steps
        if ((colIndex - 4) % 5 === 0) {
            if (rowIndex === 0) {
                return {
                    children: (
                        <div className="funnel-step-title">
                            <span className="funnel-step-glyph">{zeroPad(humanizeOrder(step?.order ?? 0), 2)}</span>
                            <PropertyKeyInfo value={step?.name ?? ''} disableIcon className="funnel-step-name" />
                        </div>
                    ),
                    props: {
                        colSpan: 5,
                        className: 'dividing-column funnel-step-title-row',
                    },
                }
            }
            return {
                children: (
                    <BreakdownBarGroupWrapper
                        dashboardItemId={dashboardItemId}
                        step={step as FunnelStepWithConversionMetrics}
                    />
                ),
                props: {
                    colSpan: 5,
                    className: 'dividing-column',
                },
            }
        }
        return {
            props: {
                colSpan: 0,
            },
        }
    }
    if (rowIndex === 2) {
        return headerElement
    }
    return defaultElement
}
