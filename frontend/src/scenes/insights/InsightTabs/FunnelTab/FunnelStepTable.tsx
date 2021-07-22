import React from 'react'
import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import Table, { ColumnsType } from 'antd/lib/table'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { SeriesToggleWrapper } from 'scenes/insights/InsightsTable/components/SeriesToggleWrapper'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTable'
import { cohortsModel } from '~/models/cohortsModel'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
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

function getCheckboxColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getColor(step, 'var(--primary)', isBreakdown)
}

export function FunnelStepTable({}: FunnelStepTableProps): JSX.Element | null {
    const { stepsWithCount, flattenedSteps, visibilityMap, filters, steps } = useValues(funnelLogic)
    const { setVisibility, openPersonsModal } = useActions(funnelLogic)
    const { cohorts } = useValues(cohortsModel)
    const tableScrollBreakpoint = getBreakpoint('lg')
    const columns: ColumnsType<FlattenedFunnelStep> = []

    columns.push({
        title: '',
        render: function RenderCheckboxOrGlyph({}, step: FlattenedFunnelStep): JSX.Element {
            if (step.breakdownIndex === undefined) {
                // Not a breakdown value; show a step-order glyph
                return <SeriesGlyph variant="funnel-step-glyph">{humanizeOrder(step.order)}</SeriesGlyph>
            }
            const isVisible = !!(step.breakdown && visibilityMap[step.breakdown])
            const color = getCheckboxColor(step, !!filters.breakdown)
            return (
                <div style={{ marginLeft: '0.15em' }}>
                    <PHCheckbox
                        color={color}
                        checked={isVisible}
                        onChange={() => step.breakdown && setVisibility(step.breakdown, !isVisible)}
                    />
                </div>
            )
        },
        fixed: 'left',
        width: 30,
    })

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
                        <div style={{ maxWidth: 270, wordBreak: 'break-word' }}>
                            {formatBreakdownLabel(step.breakdown, cohorts)}
                        </div>
                    ) : (
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
                    )}
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
                <ValueInspectorButton onClick={() => openPersonsModal(step, step.order + 1, step.breakdown)}>
                    {step.count}
                </ValueInspectorButton>
            )
        },
        width: 80,
    })

    columns.push({
        title: 'Conversion',
        render: function RenderConversion({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : <span>{step.conversionRates.total}%</span>
        },
        width: 80,
    })

    columns.push({
        title: 'Dropped off',
        render: function RenderDropoff({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : (
                <ValueInspectorButton
                    onClick={() =>
                        openPersonsModal(step, step.order + 1, step.breakdown)
                    } /* TODO: does this modal support dropped off users? */
                >
                    {step.droppedOffFromPrevious}
                </ValueInspectorButton>
            )
        },
        width: 80,
    })

    columns.push({
        title: 'From previous step',
        render: function RenderDropoffFromPrevious({}, step: FlattenedFunnelStep): JSX.Element | null {
            return step.order === 0 ? null : <span>{humanizeNumber(100 - step.conversionRates.fromPrevious, 2)}%</span>
        },
        width: 80,
    })

    columns.push({
        title: 'Average time',
        render: function RenderAverageTime({}, step: FlattenedFunnelStep): JSX.Element {
            return <span>{humanFriendlyDuration(step.average_conversion_time, 2)}</span>
        },
        width: 80,
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
