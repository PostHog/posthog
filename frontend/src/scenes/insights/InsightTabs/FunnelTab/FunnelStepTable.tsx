import React from 'react'
import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import Table, { ColumnsType } from 'antd/lib/table'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { SeriesToggleWrapper } from 'scenes/insights/InsightsTable/components/SeriesToggleWrapper'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTableV2'
import { cohortsModel } from '~/models/cohortsModel'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { FlattenedFunnelStep } from '~/types'

interface FunnelStepTableProps {
    layout?: FunnelLayout
}

function getStepColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order) || 'var(--primary)'
}

export function FunnelStepTable({ layout = FunnelLayout.horizontal }: FunnelStepTableProps): JSX.Element {
    const { flattenedSteps, visibilityMap, filters, steps } = useValues(funnelLogic)
    const { setVisibility, openPersonsModal } = useActions(funnelLogic)
    const { cohorts } = useValues(cohortsModel)
    const columns: ColumnsType<FlattenedFunnelStep> = []

    if (layout === 'horizontal') {
        columns.push({
            title: '',
            render: function RenderCheckbox({}, step: FlattenedFunnelStep): JSX.Element | null {
                if (step.breakdownIndex === undefined) {
                    // Only allow toggling breakdowns
                    return null
                }
                const isVisible = !!(step.breakdown && visibilityMap[step.breakdown])
                const color = getStepColor(step, !!filters.breakdown)
                return (
                    <PHCheckbox
                        color={color}
                        checked={isVisible}
                        onChange={() => step.breakdown && setVisibility(step.breakdown, !isVisible)}
                    />
                )
            },
            fixed: 'left',
            width: 30,
        })
    }

    columns.push({
        title: 'Step',
        render: function RenderLabel({}, step: FlattenedFunnelStep): JSX.Element {
            const isVisible = !!(step.breakdown && visibilityMap[step.breakdown])
            const isBreakdownChild = !!filters.breakdown && !step.isBreakdownParent
            const color = getStepColor(step, !!filters.breakdown)
            return (
                <SeriesToggleWrapper
                    id={step.order}
                    toggleVisibility={() => step.breakdown && setVisibility(step.breakdown, !isVisible)}
                    style={{ display: 'flex', alignItems: 'center' }}
                >
                    {isBreakdownChild ? (
                        <div style={{ maxWidth: 270, wordBreak: 'break-word', marginLeft: 30 }}>
                            {formatBreakdownLabel(step.breakdown, cohorts)}
                        </div>
                    ) : (
                        <>
                            <SeriesGlyph variant="funnel-step-glyph" style={{ marginRight: '0.5em' }}>
                                {humanizeOrder(step.order)}
                            </SeriesGlyph>
                            <div style={{ flexGrow: 1 }}>
                                <InsightLabel
                                    seriesColor={color}
                                    fallbackName={step.name}
                                    hasMultipleSeries={steps.length > 1}
                                    breakdownValue={step.breakdown}
                                    hideBreakdown
                                    hideIcon
                                />
                            </div>
                        </>
                    )}
                </SeriesToggleWrapper>
            )
        },
        fixed: 'left',
        width: 300,
    })

    columns.push({
        title: 'Completed',
        render: function RenderCompleted({}, step: FlattenedFunnelStep): JSX.Element {
            return (
                <ValueInspectorButton onClick={() => openPersonsModal(step, step.count + 1, step.breakdown_value)}>
                    {step.count}
                </ValueInspectorButton>
            )
        },
        width: 30,
    })

    columns.push({
        title: 'Conversion',
        render: function RenderConversion({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : <span>{step.conversionRates.total}%</span>
        },
        width: 30,
    })

    columns.push({
        title: 'Dropped off',
        render: function RenderDropoff({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : (
                <ValueInspectorButton
                    onClick={() =>
                        openPersonsModal(step, step.count + 1, step.breakdown_value)
                    } /* TODO: does this modal support dropped off users? */
                >
                    {step.droppedOffFromPrevious}
                </ValueInspectorButton>
            )
        },
        width: 30,
    })

    columns.push({
        title: 'From previous',
        render: function RenderDropoffFromPrevious({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : <span>{humanizeNumber(100 - step.conversionRates.fromPrevious, 2)}%</span>
        },
        width: 30,
    })

    columns.push({
        title: 'Mean time',
        render: function RenderAverageTime({}, step: FlattenedFunnelStep): JSX.Element {
            return <span>{humanFriendlyDuration(step.average_conversion_time, 2)}</span>
        },
        width: 30,
    })

    return (
        <Table
            dataSource={flattenedSteps}
            columns={columns}
            size="small"
            rowKey="rowKey"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            data-attr="funnel-steps-table"
        />
    )
}
