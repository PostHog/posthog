import React from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { TableProps } from 'antd'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import Table, { ColumnsType } from 'antd/lib/table'
import { FlagOutlined, UserOutlined, UserDeleteOutlined } from '@ant-design/icons'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTable'
import { cohortsModel } from '~/models/cohortsModel'
import { IconSize, InsightLabel } from 'lib/components/InsightLabel'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { formatDisplayPercentage, getSeriesColor, getVisibilityIndex, humanizeOrder } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils'
import { FlattenedFunnelStep, FlattenedFunnelStepByBreakdown } from '~/types'
import { PHCheckbox } from 'lib/components/PHCheckbox'
import {
    EmptyValue,
    getActionFilterFromFunnelStep,
    getSignificanceFromBreakdownStep,
    getStepColor,
    isBreakdownChildType,
    renderColumnTitle,
    renderGraphAndHeader,
    renderSubColumnTitle,
} from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import './FunnelStepTable.scss'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Tooltip } from 'lib/components/Tooltip'

export function FunnelStepTable(): JSX.Element | null {
    const { insightProps, isViewedOnDashboard } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        stepsWithCount,
        flattenedSteps,
        steps,
        visibleStepsWithConversionMetrics,
        hiddenLegendKeys,
        barGraphLayout,
        flattenedStepsByBreakdown,
        flattenedBreakdowns,
        aggregationTargetLabel,
        isModalActive,
    } = useValues(logic)
    const { openPersonsModalForStep, toggleVisibilityByBreakdown, setHiddenById } = useActions(logic)
    const { cohorts } = useValues(cohortsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const isNewVertical =
        featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] && barGraphLayout === FunnelLayout.vertical
    const showLabels = (visibleStepsWithConversionMetrics?.[0]?.nested_breakdown?.length ?? 0) < 6

    function getColumns(): ColumnsType<FlattenedFunnelStep> | ColumnsType<FlattenedFunnelStepByBreakdown> {
        if (isNewVertical) {
            const _columns: ColumnsType<FlattenedFunnelStepByBreakdown> = []
            const isOnlySeries = flattenedBreakdowns.length === 1

            if (!isViewedOnDashboard) {
                _columns.push({
                    render: function RenderCheckbox({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                        const checked = !!flattenedBreakdowns?.every(
                            (b) =>
                                !hiddenLegendKeys[
                                    getVisibilityIndex(visibleStepsWithConversionMetrics?.[0], b.breakdown_value)
                                ]
                        )
                        const color = getSeriesColor(breakdown?.breakdownIndex, isOnlySeries)

                        return renderGraphAndHeader(
                            rowIndex,
                            0,
                            <PHCheckbox
                                color={color}
                                checked={
                                    !hiddenLegendKeys[
                                        getVisibilityIndex(
                                            visibleStepsWithConversionMetrics?.[0],
                                            breakdown.breakdown_value
                                        )
                                    ]
                                } // assume visible status from first step's visibility
                                onChange={() => toggleVisibilityByBreakdown(breakdown.breakdown_value)}
                            />,
                            <PHCheckbox
                                color={isOnlySeries ? 'var(--primary)' : undefined}
                                checked={checked}
                                indeterminate={flattenedBreakdowns?.some(
                                    (b) =>
                                        !hiddenLegendKeys[
                                            getVisibilityIndex(
                                                visibleStepsWithConversionMetrics?.[0],
                                                b.breakdown_value
                                            )
                                        ]
                                )}
                                onChange={() => {
                                    // either toggle all data on or off
                                    setHiddenById(
                                        Object.fromEntries(
                                            visibleStepsWithConversionMetrics.flatMap((s) =>
                                                flattenedBreakdowns.map((b) => [
                                                    getVisibilityIndex(s, b.breakdown_value),
                                                    checked,
                                                ])
                                            )
                                        )
                                    )
                                }}
                            />,
                            showLabels,
                            undefined,
                            isViewedOnDashboard
                        )
                    },
                    fixed: 'left',
                    width: 20,
                    align: 'center',
                })

                _columns.push({
                    render: function RenderLabel({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                        const color = getSeriesColor(breakdown?.breakdownIndex, isOnlySeries)

                        return renderGraphAndHeader(
                            rowIndex,
                            1,
                            <InsightLabel
                                seriesColor={color}
                                fallbackName={formatBreakdownLabel(
                                    cohorts,
                                    isOnlySeries ? `Unique ${aggregationTargetLabel.plural}` : breakdown.breakdown_value
                                )}
                                hasMultipleSeries={steps.length > 1}
                                breakdownValue={breakdown.breakdown_value}
                                hideBreakdown={false}
                                iconSize={IconSize.Small}
                                iconStyle={{ marginRight: 12 }}
                                allowWrap
                                hideIcon
                            />,
                            renderColumnTitle('Breakdown'),
                            showLabels,
                            undefined,
                            isViewedOnDashboard
                        )
                    },
                    fixed: 'left',
                    width: 150,
                    className: 'funnel-table-cell breakdown-label-column',
                })

                _columns.push({
                    render: function RenderCompletionRate({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                        return renderGraphAndHeader(
                            rowIndex,
                            2,
                            <span>{formatDisplayPercentage(breakdown?.conversionRates?.total ?? 0)}%</span>,
                            renderSubColumnTitle('Rate'),
                            showLabels,
                            undefined,
                            isViewedOnDashboard
                        )
                    },
                    fixed: 'left',
                    width: 120,
                    align: 'right',
                    className: 'funnel-table-cell dividing-column',
                })
            }

            // Add columns per step
            visibleStepsWithConversionMetrics.forEach((step, stepIndex) => {
                _columns.push({
                    render: function RenderCompleted({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                        const breakdownStep = breakdown.steps?.[step.order]
                        return renderGraphAndHeader(
                            rowIndex,
                            step.order === 0 ? 3 : (stepIndex - 1) * 5 + 5,
                            breakdownStep?.count != undefined ? (
                                <ValueInspectorButton
                                    onClick={() => openPersonsModalForStep({ step: breakdownStep, converted: true })}
                                    disabled={!isModalActive}
                                >
                                    {breakdown.steps?.[step.order].count}
                                </ValueInspectorButton>
                            ) : (
                                EmptyValue
                            ),
                            renderSubColumnTitle(
                                <>
                                    <UserOutlined
                                        title={`Unique ${aggregationTargetLabel.plural} who completed this step`}
                                    />{' '}
                                    Completed
                                </>
                            ),
                            showLabels,
                            step,
                            isViewedOnDashboard
                        )
                    },
                    width: 80,
                    align: 'right',
                })

                _columns.push({
                    render: function RenderConversion({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                        return renderGraphAndHeader(
                            rowIndex,
                            step.order === 0 ? 4 : (stepIndex - 1) * 5 + 6,
                            breakdown.steps?.[step.order]?.conversionRates.fromBasisStep != undefined ? (
                                <>
                                    {featureFlags[FEATURE_FLAGS.SIGMA_ANALYSIS] &&
                                    getSignificanceFromBreakdownStep(breakdown, step.order)?.fromBasisStep ? (
                                        <Tooltip title="Significantly different from other breakdown values">
                                            <span className="table-text-highlight">
                                                <FlagOutlined style={{ marginRight: 2 }} />{' '}
                                                {formatDisplayPercentage(
                                                    breakdown.steps?.[step.order]?.conversionRates.fromBasisStep
                                                )}
                                                %
                                            </span>
                                        </Tooltip>
                                    ) : (
                                        <span>
                                            {formatDisplayPercentage(
                                                breakdown.steps?.[step.order]?.conversionRates.fromBasisStep
                                            )}
                                            %
                                        </span>
                                    )}
                                </>
                            ) : (
                                EmptyValue
                            ),
                            renderSubColumnTitle('Rate'),
                            showLabels,
                            step,
                            isViewedOnDashboard
                        )
                    },
                    width: 80,
                    align: 'right',
                    className: step.order === 0 ? 'funnel-table-cell dividing-column' : undefined,
                })

                if (step.order !== 0) {
                    _columns.push({
                        render: function RenderDropoff({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                            const breakdownStep = breakdown.steps?.[step.order]
                            return renderGraphAndHeader(
                                rowIndex,
                                (stepIndex - 1) * 5 + 7,
                                breakdownStep?.droppedOffFromPrevious != undefined ? (
                                    <ValueInspectorButton
                                        onClick={() =>
                                            openPersonsModalForStep({
                                                step: breakdownStep,
                                                converted: false,
                                            })
                                        }
                                        disabled={!isModalActive}
                                    >
                                        {breakdown.steps?.[step.order]?.droppedOffFromPrevious}
                                    </ValueInspectorButton>
                                ) : (
                                    EmptyValue
                                ),
                                renderSubColumnTitle(
                                    <>
                                        <UserDeleteOutlined
                                            title={`Unique ${aggregationTargetLabel.plural} who dropped off on this step`}
                                        />{' '}
                                        Dropped
                                    </>
                                ),
                                showLabels,
                                step,
                                isViewedOnDashboard
                            )
                        },
                        width: 80,
                        align: 'right',
                    })

                    _columns.push({
                        render: function RenderDropoffRate({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                            return renderGraphAndHeader(
                                rowIndex,
                                (stepIndex - 1) * 5 + 8,
                                breakdown.steps?.[step.order]?.conversionRates.fromPrevious != undefined ? (
                                    <>
                                        {featureFlags[FEATURE_FLAGS.SIGMA_ANALYSIS] &&
                                        !getSignificanceFromBreakdownStep(breakdown, step.order)?.fromBasisStep &&
                                        getSignificanceFromBreakdownStep(breakdown, step.order)?.fromPrevious ? (
                                            <Tooltip title="Significantly different from other breakdown values">
                                                <span className="table-text-highlight">
                                                    <FlagOutlined style={{ marginRight: 2 }} />{' '}
                                                    {formatDisplayPercentage(
                                                        1 - breakdown.steps?.[step.order]?.conversionRates.fromPrevious
                                                    )}
                                                    %
                                                </span>
                                            </Tooltip>
                                        ) : (
                                            <span>
                                                {formatDisplayPercentage(
                                                    1 - breakdown.steps?.[step.order]?.conversionRates.fromPrevious
                                                )}
                                                %
                                            </span>
                                        )}
                                    </>
                                ) : (
                                    EmptyValue
                                ),
                                renderSubColumnTitle('Rate'),
                                showLabels,
                                step,
                                isViewedOnDashboard
                            )
                        },
                        width: 80,
                        align: 'right',
                    })

                    _columns.push({
                        render: function RenderAverageTime({}, breakdown: FlattenedFunnelStepByBreakdown, rowIndex) {
                            return renderGraphAndHeader(
                                rowIndex,
                                (stepIndex - 1) * 5 + 9,
                                breakdown.steps?.[step.order]?.average_conversion_time != undefined ? (
                                    <span>
                                        {colonDelimitedDuration(
                                            breakdown.steps?.[step.order]?.average_conversion_time,
                                            3
                                        )}
                                    </span>
                                ) : (
                                    EmptyValue
                                ),
                                renderSubColumnTitle('Avg. time'),
                                showLabels,
                                step,
                                isViewedOnDashboard
                            )
                        },
                        width: 80,
                        align: 'right',
                        className: 'funnel-table-cell dividing-column',
                    })
                }
            })

            return _columns
        }

        // If steps are horizontal, render table with flattened steps

        const _columns: ColumnsType<FlattenedFunnelStep> = []
        _columns.push({
            title: '',
            render: function RenderSeriesGlyph({}, step: FlattenedFunnelStep): JSX.Element | null {
                if (step.breakdownIndex === undefined) {
                    // Not a breakdown value; show a step-order glyph
                    return <SeriesGlyph variant="funnel-step-glyph">{humanizeOrder(step.order)}</SeriesGlyph>
                }
                return null
            },
            fixed: 'left',
            width: 20,
            align: 'center',
        })

        if (featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] && !!steps[0]?.breakdown) {
            _columns.push({
                title: '',
                render: function RenderCheckbox({}, step: FlattenedFunnelStep): JSX.Element | null {
                    // Breakdown parent
                    if (step.breakdownIndex === undefined && (step.nestedRowKeys ?? []).length > 0) {
                        return (
                            <PHCheckbox
                                checked={!!step.nestedRowKeys?.every((rowKey) => !hiddenLegendKeys[rowKey])}
                                indeterminate={step.nestedRowKeys?.some((rowKey) => !hiddenLegendKeys[rowKey])}
                                onChange={() => {
                                    // either toggle all data on or off
                                    const currentState = !!step.nestedRowKeys?.every(
                                        (rowKey) => !hiddenLegendKeys[rowKey]
                                    )
                                    setHiddenById(
                                        Object.fromEntries(
                                            (flattenedSteps?.filter((s) => s.breakdownIndex !== undefined) ?? []).map(
                                                ({ rowKey }) => [rowKey, !currentState]
                                            )
                                        )
                                    )
                                }}
                            />
                        )
                    }
                    // Breakdown child
                    return (
                        <PHCheckbox
                            checked={!hiddenLegendKeys[step.rowKey]}
                            onChange={() => toggleVisibilityByBreakdown(step.breakdownIndex as number)}
                        />
                    )
                },
                fixed: 'left',
                width: 20,
                align: 'center',
            })
        }

        _columns.push({
            title: 'Step',
            render: function RenderLabel({}, step: FlattenedFunnelStep): JSX.Element {
                const isBreakdownChild = !!step.breakdown && !step.isBreakdownParent
                const color = getStepColor(step, !!step.breakdown)

                return (
                    <InsightLabel
                        seriesColor={color}
                        fallbackName={
                            isBreakdownChild && isBreakdownChildType(step.breakdown)
                                ? formatBreakdownLabel(cohorts, step.breakdown)
                                : step.name
                        }
                        action={
                            isBreakdownChild && isBreakdownChildType(step.breakdown)
                                ? undefined
                                : getActionFilterFromFunnelStep(step)
                        }
                        hasMultipleSeries={!isBreakdownChild && steps.length > 1}
                        breakdownValue={
                            step.breakdown === ''
                                ? 'None'
                                : isBreakdownChildType(step.breakdown)
                                ? step.breakdown
                                : undefined
                        }
                        hideBreakdown={!isBreakdownChild}
                        iconSize={IconSize.Small}
                        iconStyle={{ marginRight: 12 }}
                        hideIcon={!isBreakdownChild}
                        allowWrap
                        useCustomName
                    />
                )
            },
            fixed: 'left',
            width: 120,
        })

        _columns.push({
            title: 'Completed',
            render: function RenderCompleted({}, step: FlattenedFunnelStep): JSX.Element {
                return (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, converted: true })}
                        disabled={!isModalActive}
                    >
                        {step.count}
                    </ValueInspectorButton>
                )
            },
            width: 80,
            align: 'center',
        })

        _columns.push({
            title: 'Conversion',
            render: function RenderConversion({}, step: FlattenedFunnelStep): JSX.Element | null {
                return step.order === 0 ? (
                    EmptyValue
                ) : (
                    <span>{formatDisplayPercentage(step.conversionRates.total)}%</span>
                )
            },
            width: 80,
            align: 'center',
        })

        _columns.push({
            title: 'Dropped off',
            render: function RenderDropoff({}, step: FlattenedFunnelStep): JSX.Element | null {
                return step.order === 0 ? (
                    EmptyValue
                ) : (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, converted: false })}
                        disabled={!isModalActive}
                    >
                        {step.droppedOffFromPrevious}
                    </ValueInspectorButton>
                )
            },
            width: 80,
            align: 'center',
        })

        _columns.push({
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

        _columns.push({
            title: 'Average time',
            render: function RenderAverageTime({}, step: FlattenedFunnelStep): JSX.Element {
                return step.average_conversion_time ? (
                    <span>{humanFriendlyDuration(step.average_conversion_time, 2)}</span>
                ) : (
                    EmptyValue
                )
            },
            width: 100,
            align: 'center',
        })

        return _columns
    }

    // If the bars are vertical, use table as legend #5733
    const columns = getColumns()
    const tableData: TableProps<any /* TODO: Type this */> = isNewVertical
        ? {
              dataSource: flattenedStepsByBreakdown.slice(
                  0,
                  isViewedOnDashboard ? 2 : flattenedStepsByBreakdown.length
              ),
              columns,
              showHeader: false,
              rowClassName: (record, index) => {
                  return clsx(
                      `funnel-steps-table-row-${index}`,
                      index === 2 && 'funnel-table-cell',
                      featureFlags[FEATURE_FLAGS.SIGMA_ANALYSIS] && record.significant && 'table-cell-highlight'
                  )
              },
          }
        : {
              dataSource: flattenedSteps,
              columns,
          }

    return stepsWithCount.length > 1 ? (
        <Table
            {...tableData}
            scroll={isViewedOnDashboard ? undefined : { x: 'max-content' }}
            size="small"
            rowKey="rowKey"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            style={{ height: '100%' }}
            data-attr={isNewVertical ? 'funnel-bar-graph' : 'funnel-steps-table'}
            className="funnel-steps-table"
        />
    ) : null
}
