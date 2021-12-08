import {
    ActionFilter,
    FlattenedFunnelStep,
    FlattenedFunnelStepByBreakdown,
    FunnelStep,
    FunnelStepWithConversionMetrics,
} from '~/types'
import { getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { RenderedCell } from 'rc-table/lib/interface'
import React from 'react'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { zeroPad } from 'lib/utils'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FunnelStepDropdown } from 'scenes/funnels/FunnelStepDropdown'
import { BreakdownBarGroupWrapper } from 'scenes/insights/InsightTabs/FunnelTab/FunnelBreakdown'

export function getColor(step: FlattenedFunnelStep, fallbackColor: string, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order, false, fallbackColor)
}

export function getStepColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getColor(step, 'var(--text-default)', isBreakdown)
}

/**
 * While we have both multi and single property breakdown modes.
 * And FlattenedFunnelStep['breakdowns'] property is being copied onto FlattenedFunnelStep['breakdown']
 * This might receive an Array of strings
 * @param stepBreakdown
 */
export function isBreakdownChildType(
    stepBreakdown: FlattenedFunnelStep['breakdown'] | Array<string | number>
): stepBreakdown is string | number | undefined | Array<string | number> {
    return Array.isArray(stepBreakdown) || ['string', 'number', 'undefined'].includes(typeof stepBreakdown)
}

export const renderSubColumnTitle = (title: string | JSX.Element): JSX.Element => (
    <span className="sub-column-title">{title}</span>
)

export const renderColumnTitle = (title: string): JSX.Element => <span className="column-title">{title}</span>

export const EmptyValue = <span className="text-muted-alt">-</span>

export const renderGraphAndHeader = (
    rowIndex: number,
    colIndex: number,
    defaultElement: JSX.Element,
    headerElement: JSX.Element,
    showLabels: boolean,
    step?: FunnelStepWithConversionMetrics,
    isViewedOnDashboard: boolean = false
): JSX.Element | RenderedCell<FlattenedFunnelStepByBreakdown> => {
    const stepIndex = step?.order ?? 0
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
                            <span className="funnel-step-glyph">{zeroPad(humanizeOrder(stepIndex), 2)}</span>
                            {step && <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />}
                            <FunnelStepDropdown index={stepIndex} />
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
                    <BreakdownBarGroupWrapper step={step as FunnelStepWithConversionMetrics} showLabels={showLabels} />
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
                            <span className="funnel-step-glyph">{zeroPad(humanizeOrder(stepIndex), 2)}</span>
                            <PropertyKeyInfo value={step?.name ?? ''} disableIcon className="funnel-step-name" />
                            <FunnelStepDropdown index={stepIndex} />
                        </div>
                    ),
                    props: {
                        colSpan: isViewedOnDashboard ? 2 : 5,
                        className: 'funnel-table-cell dividing-column funnel-step-title-row',
                    },
                }
            }
            return {
                children: (
                    <BreakdownBarGroupWrapper step={step as FunnelStepWithConversionMetrics} showLabels={showLabels} />
                ),
                props: {
                    colSpan: isViewedOnDashboard ? 2 : 5,
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

export function getSignificanceFromBreakdownStep(
    breakdown: FlattenedFunnelStepByBreakdown,
    stepOrder: number
): FunnelStepWithConversionMetrics['significant'] {
    return breakdown.steps?.[stepOrder].significant
}
