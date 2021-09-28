import {
    ActionFilter,
    FlattenedFunnelStep,
    FlattenedFunnelStepByBreakdown,
    FunnelStep,
    FunnelStepWithConversionMetrics,
} from '~/types'
import { getReferenceStep, getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { RenderedCell } from 'rc-table/lib/interface'
import React from 'react'
import { BreakdownVerticalBarGroup } from 'scenes/funnels/FunnelBarGraph'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { zeroPad } from 'lib/utils'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'

export function getColor(step: FlattenedFunnelStep, fallbackColor: string, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order, false, fallbackColor)
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
    showLabels,
}: {
    step: FunnelStepWithConversionMetrics
    dashboardItemId?: number
    showLabels: boolean
}): JSX.Element {
    const logic = funnelLogic({ dashboardItemId })
    const {
        stepReference,
        visibleStepsWithConversionMetrics: steps,
        clickhouseFeaturesEnabled,
        flattenedBreakdowns,
    } = useValues(logic)
    const { openPersonsModal } = useActions(logic)
    const basisStep = getReferenceStep(steps, stepReference, step.order)
    const previousStep = getReferenceStep(steps, FunnelStepReference.previous, step.order)
    const isClickable = !!(clickhouseFeaturesEnabled && !dashboardItemId && openPersonsModal)

    return (
        <div className="funnel-bar-wrapper breakdown vertical">
            <BreakdownVerticalBarGroup
                currentStep={step}
                basisStep={basisStep}
                previousStep={previousStep}
                showLabels={showLabels}
                onBarClick={(breakdown_value) => {
                    if (isClickable) {
                        openPersonsModal(step, step.order + 1, breakdown_value)
                    }
                }}
                isClickable={isClickable}
                isSingleSeries={flattenedBreakdowns.length === 1}
            />
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
    showLabels: boolean,
    step?: FunnelStepWithConversionMetrics,
    dashboardItemId?: number,
    useCustomName?: boolean
): JSX.Element | RenderedCell<FlattenedFunnelStepByBreakdown> => {
    if (rowIndex === 0 || rowIndex === 1) {
        // Empty cell
        if (colIndex === 0) {
            if (rowIndex === 0) {
                return {
                    props: {
                        colSpan: 3,
                        className: 'funnel-table-cell dividing-column no-border-bottom dark-bg',
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
                    className: 'funnel-table-cell dividing-column axis-labels-column dark-bg',
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
                            {useCustomName && step ? (
                                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                            ) : (
                                <PropertyKeyInfo value={step?.name ?? ''} disableIcon className="funnel-step-name" />
                            )}
                        </div>
                    ),
                    props: {
                        colSpan: 2,
                        className: 'funnel-table-cell dividing-column funnel-step-title-row',
                    },
                }
            }
            return {
                children: (
                    <BreakdownBarGroupWrapper
                        dashboardItemId={dashboardItemId}
                        step={step as FunnelStepWithConversionMetrics}
                        showLabels={showLabels}
                    />
                ),
                props: {
                    colSpan: 2,
                    className: 'funnel-table-cell dividing-column dark-bg',
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
                        className: 'funnel-table-cell dividing-column funnel-step-title-row',
                    },
                }
            }
            return {
                children: (
                    <BreakdownBarGroupWrapper
                        dashboardItemId={dashboardItemId}
                        step={step as FunnelStepWithConversionMetrics}
                        showLabels={showLabels}
                    />
                ),
                props: {
                    colSpan: 5,
                    className: 'funnel-table-cell dividing-column dark-bg',
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

export function getActionFilterFromFunnelStep(step: FunnelStep): ActionFilter {
    return {
        type: step.type,
        id: step.action_id,
        name: step.name,
        custom_name: step.custom_name,
        order: step.order,
        properties: [],
    }
}
