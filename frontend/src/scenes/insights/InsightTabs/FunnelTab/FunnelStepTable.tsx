import React from 'react'
import { useActions, useValues } from 'kea'
import { FunnelLayout } from 'lib/constants'
import {
    funnelLogic,
    isBreakdownVisibilityMap,
    StepVisibilityMap,
    FlattenedFunnelStep,
} from 'scenes/funnels/funnelLogic'
import Table, { ColumnsType } from 'antd/lib/table'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import { SeriesToggleWrapper } from 'scenes/insights/InsightsTable/components/SeriesToggleWrapper'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTableV2'
import { cohortsModel } from '~/models/cohortsModel'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { getSeriesColor, humanizeOrder } from 'scenes/funnels/funnelUtils'

interface FunnelStepTableProps {
    layout?: FunnelLayout
}

// If kea selectors accepted params, this could be moved to funnelLogic
const stepVisibilityLookup = (visibilityMap: StepVisibilityMap) => (index: number, breakdown?: string) => {
    if (breakdown) {
        const breakdownMap = visibilityMap[index]
        if (isBreakdownVisibilityMap(breakdownMap)) {
            return breakdownMap?.[breakdown] ?? true
        }
    }
    return Boolean(visibilityMap[index] ?? true)
}

function getStepColor(step: FlattenedFunnelStep, isBreakdown?: boolean): string {
    return getSeriesColor(isBreakdown ? step.breakdownIndex : step.order) || 'var(--primary)'
}

export function FunnelStepTable({ layout = FunnelLayout.horizontal }: FunnelStepTableProps): JSX.Element {
    const { flattenedSteps, visibilityMap, filters, steps } = useValues(funnelLogic)
    const { setVisibilityByIndex } = useActions(funnelLogic)
    const { cohorts } = useValues(cohortsModel)
    const isStepVisible = stepVisibilityLookup(visibilityMap)
    const columns: ColumnsType<FlattenedFunnelStep> = []

    if (layout === 'horizontal') {
        columns.push({
            title: '',
            render: function RenderCheckbox({}, step: FlattenedFunnelStep) {
                // legend will always be on insight page where the background is white
                const isVisible = isStepVisible(step.order, step.breakdown)
                const color = getStepColor(step, !!filters.breakdown)
                return (
                    <PHCheckbox
                        color={color}
                        checked={isVisible}
                        onChange={() => setVisibilityByIndex(step.order, !isVisible, step.breakdown)}
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
            const isVisible = isStepVisible(step.order, step.breakdown)
            const isBreakdownChild = !!filters.breakdown && !step.isBreakdownParent
            const color = getStepColor(step, !!filters.breakdown)
            return (
                <SeriesToggleWrapper
                    id={step.order}
                    toggleVisibility={() => setVisibilityByIndex(step.order, !isVisible, step.breakdown)}
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

    return (
        <Table
            dataSource={flattenedSteps}
            columns={columns}
            size="small"
            rowKey="order"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
            data-attr="funnel-steps-table"
        />
    )
}
