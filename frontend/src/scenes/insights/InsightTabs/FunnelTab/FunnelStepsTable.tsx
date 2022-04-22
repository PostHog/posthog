import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/components/LemonTable'
import { BreakdownKeyType, FlattenedFunnelStepByBreakdown } from '~/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { formatDisplayPercentage, getSeriesColor, getVisibilityIndex } from 'scenes/funnels/funnelUtils'
import { getActionFilterFromFunnelStep } from './funnelStepTableUtils'
import { formatBreakdownLabel } from 'scenes/insights/InsightsTable/InsightsTable'
import { cohortsModel } from '~/models/cohortsModel'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { LemonRow } from 'lib/components/LemonRow'
import { humanFriendlyDuration } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { insightLoading, steps, flattenedBreakdowns, hiddenLegendKeys, visibleStepsWithConversionMetrics } =
        useValues(logic)
    const { setHiddenById, toggleVisibilityByBreakdown, openPersonsModalForStep } = useActions(logic)
    const { cohorts } = useValues(cohortsModel)

    const isOnlySeries = flattenedBreakdowns.length === 1
    const allChecked = flattenedBreakdowns?.every(
        (b) => !hiddenLegendKeys[getVisibilityIndex(visibleStepsWithConversionMetrics?.[0], b.breakdown_value)]
    )

    const columnsGrouped = [
        {
            children: [
                {
                    title: isOnlySeries ? (
                        'Breakdown'
                    ) : (
                        <LemonCheckbox
                            checked={
                                allChecked ||
                                (flattenedBreakdowns?.some(
                                    (b) =>
                                        !hiddenLegendKeys[
                                            getVisibilityIndex(
                                                visibleStepsWithConversionMetrics?.[0],
                                                b.breakdown_value
                                            )
                                        ]
                                )
                                    ? 'indeterminate'
                                    : false)
                            }
                            onChange={() => {
                                // Either toggle all data on or off
                                setHiddenById(
                                    Object.fromEntries(
                                        visibleStepsWithConversionMetrics.flatMap((s) =>
                                            flattenedBreakdowns.map((b) => [
                                                getVisibilityIndex(s, b.breakdown_value),
                                                allChecked,
                                            ])
                                        )
                                    )
                                )
                            }}
                            label="Breakdown"
                            rowProps={{ compact: true, style: { padding: 0, marginLeft: '-0.5rem', font: 'inherit' } }}
                        />
                    ),
                    dataIndex: 'breakdown_value',
                    render: function RenderBreakdownValue(breakdownValue: BreakdownKeyType | undefined): JSX.Element {
                        const label = formatBreakdownLabel(cohorts, breakdownValue)
                        return isOnlySeries ? (
                            <span style={{ fontWeight: 500 }}>{label}</span>
                        ) : (
                            <LemonCheckbox
                                checked={
                                    !hiddenLegendKeys[
                                        getVisibilityIndex(visibleStepsWithConversionMetrics?.[0], breakdownValue)
                                    ]
                                } // assume visible status from first step's visibility
                                onChange={() => toggleVisibilityByBreakdown(breakdownValue)}
                                label={label}
                                rowProps={{
                                    compact: true,
                                    style: { padding: 0, marginLeft: '-0.5rem', maxWidth: '16rem' },
                                    title: label,
                                }}
                            />
                        )
                    },
                },
                {
                    title: 'Total conversion',
                    render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                        formatDisplayPercentage(breakdown?.conversionRates?.total ?? 0, true),
                    align: 'right',
                },
            ],
        },
        ...steps.map((step, stepIndex) => ({
            title: (
                <LemonRow
                    icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} double />}
                    style={{ font: 'inherit', padding: 0 }}
                    compact
                >
                    <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                </LemonRow>
            ),
            children: [
                {
                    title: 'Completed',
                    render: function RenderCompleted(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element | undefined {
                        const stepSeries = breakdown.steps?.[stepIndex]
                        return (
                            stepSeries && (
                                <ValueInspectorButton
                                    onClick={() => openPersonsModalForStep({ step: stepSeries, converted: true })}
                                    style={{ padding: 0 }}
                                >
                                    {stepSeries.count ?? 0}
                                </ValueInspectorButton>
                            )
                        )
                    },

                    align: 'right',
                },
                {
                    title: 'Rate',
                    render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                        formatDisplayPercentage(breakdown.steps?.[stepIndex]?.conversionRates.fromPrevious ?? 0, true),
                    align: 'right',
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: 'Dropped',
                              render: function RenderDropped(
                                  _: void,
                                  breakdown: FlattenedFunnelStepByBreakdown
                              ): JSX.Element | undefined {
                                  const stepSeries = breakdown.steps?.[stepIndex]
                                  return (
                                      stepSeries && (
                                          <ValueInspectorButton
                                              onClick={() =>
                                                  openPersonsModalForStep({ step: stepSeries, converted: false })
                                              }
                                              style={{ padding: 0 }}
                                          >
                                              {stepSeries.droppedOffFromPrevious ?? 0}
                                          </ValueInspectorButton>
                                      )
                                  )
                              },
                              align: 'right',
                          },
                          {
                              title: 'Rate',
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  formatDisplayPercentage(
                                      1 - (breakdown.steps?.[stepIndex]?.conversionRates.fromPrevious ?? 0),
                                      true
                                  ),
                              align: 'right',
                          },
                          {
                              title: 'Avg. time',
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.average_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].average_conversion_time, 3)
                                      : '–',
                              align: 'right',
                              className: 'nowrap',
                          },
                      ]),
            ] as LemonTableColumn<FlattenedFunnelStepByBreakdown, keyof FlattenedFunnelStepByBreakdown>[],
        })),
    ] as LemonTableColumnGroup<FlattenedFunnelStepByBreakdown>[]

    return (
        <LemonTable
            dataSource={flattenedBreakdowns}
            columns={columnsGrouped}
            loading={insightLoading}
            rowRibbonColor={(series) =>
                getSeriesColor(
                    series?.breakdownIndex,
                    flattenedBreakdowns.length === 1,
                    undefined,
                    flattenedBreakdowns.length
                )
            }
            rowKey="breakdownIndex"
        />
    )
}
