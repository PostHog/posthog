import React from 'react'
import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import Table, { ColumnsType } from 'antd/lib/table'
import { SeriesToggleWrapper } from 'scenes/insights/InsightsTable/components/SeriesToggleWrapper'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTable'
import { cohortsModel } from '~/models/cohortsModel'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { formatDisplayPercentage, getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { humanFriendlyDuration } from 'lib/utils'
import { FlattenedFunnelStep } from '~/types'
import { getBreakpoint } from 'lib/utils/responsiveUtils'

interface FunnelStepTableProps {
    layout?: FunnelLayout // Not yet implemented
}

function getColor(step: FlattenedFunnelStep, fallbackColor: string, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order) || fallbackColor
}

function getStepColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getColor(step, 'var(--text-default)', isBreakdown)
}

function isBreakdownChildType(
    stepBreakdown: FlattenedFunnelStep['breakdown']
): stepBreakdown is string | number | undefined {
    return ['string', 'number', 'undefined'].includes(typeof stepBreakdown)
}

export function FunnelStepTable({}: FunnelStepTableProps): JSX.Element | null {
    const { stepsWithCount, flattenedSteps, filters, steps } = useValues(funnelLogic)
    const { openPersonsModal } = useActions(funnelLogic)
    const { cohorts } = useValues(cohortsModel)
    const tableScrollBreakpoint = getBreakpoint('lg')
    const columns: ColumnsType<FlattenedFunnelStep> = []

    const EmptyValue = <span className="text-muted-alt">-</span>

    columns.push({
        title: '',
        render: function RenderSeriesGlyph({}, step: FlattenedFunnelStep): JSX.Element | null {
            if (step.breakdownIndex === undefined) {
                // Not a breakdown value; show a step-order glyph
                return <SeriesGlyph variant="funnel-step-glyph">{humanizeOrder(step.order)}</SeriesGlyph>
            }
            return null
        },
        fixed: 'left',
        width: 30,
        align: 'center',
    })

    columns.push({
        title: 'Step',
        render: function RenderLabel({}, step: FlattenedFunnelStep): JSX.Element {
            const isBreakdownChild = !!filters.breakdown && !step.isBreakdownParent
            const color = getStepColor(step, !!filters.breakdown)
            return (
                <SeriesToggleWrapper id={step.order} style={{ display: 'flex', alignItems: 'center' }}>
                    <div style={{ flexGrow: 1, maxWidth: 270, wordBreak: 'break-word' }}>
                        <InsightLabel
                            seriesColor={color}
                            fallbackName={
                                isBreakdownChild && isBreakdownChildType(step.breakdown)
                                    ? formatBreakdownLabel(step.breakdown, cohorts)
                                    : step.name
                            }
                            hasMultipleSeries={steps.length > 1}
                            breakdownValue={
                                step.breakdown === ''
                                    ? 'None'
                                    : isBreakdownChildType(step.breakdown)
                                    ? step.breakdown
                                    : undefined
                            }
                            hideBreakdown
                            hideIcon={!isBreakdownChild}
                            allowWrap
                        />
                    </div>
                </SeriesToggleWrapper>
            )
        },
        fixed: 'left',
        width: 120,
    })

    columns.push({
        title: 'Completed',
        render: function RenderCompleted({}, step: FlattenedFunnelStep): JSX.Element {
            return (
                <ValueInspectorButton
                    onClick={() =>
                        openPersonsModal(
                            step,
                            step.order + 1,
                            step.isBreakdownParent ? undefined : step.breakdown_value
                        )
                    }
                >
                    {step.count}
                </ValueInspectorButton>
            )
        },
        width: 80,
        align: 'center',
    })

    columns.push({
        title: 'Conversion',
        render: function RenderConversion({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? EmptyValue : <span>{formatDisplayPercentage(step.conversionRates.total)}%</span>
        },
        width: 80,
        align: 'center',
    })

    columns.push({
        title: 'Dropped off',
        render: function RenderDropoff({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? (
                EmptyValue
            ) : (
                <ValueInspectorButton
                    onClick={() =>
                        openPersonsModal(
                            step,
                            -(step.order + 1),
                            step.isBreakdownParent ? undefined : step.breakdown_value
                        )
                    }
                >
                    {step.droppedOffFromPrevious}
                </ValueInspectorButton>
            )
        },
        width: 80,
        align: 'center',
    })

    columns.push({
        title: 'From previous step',
        render: function RenderDropoffFromPrevious({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? (
                EmptyValue
            ) : (
                <span>{formatDisplayPercentage(1 - step.conversionRates.fromPrevious)}%</span>
            )
        },
        width: 80,
        align: 'center',
    })

    columns.push({
        title: 'Average time',
        render: function RenderAverageTime({}, step: FlattenedFunnelStep): JSX.Element {
            return step.average_conversion_time ? (
                <span>{humanFriendlyDuration(step.average_conversion_time, 2)}</span>
            ) : (
                EmptyValue
            )
        },
        width: 80,
        align: 'center',
    })

    return stepsWithCount.length > 1 ? (
        <Table
            dataSource={flattenedSteps}
            columns={columns}
            scroll={{ x: `${tableScrollBreakpoint}px` }}
            size="small"
            rowKey="rowKey"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            data-attr="funnel-steps-table"
        />
    ) : null
}
