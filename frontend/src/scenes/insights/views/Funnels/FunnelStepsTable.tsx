import React from 'react'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/components/LemonTable'
import { BreakdownKeyType, FlattenedFunnelStepByBreakdown } from '~/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getVisibilityIndex } from 'scenes/funnels/funnelUtils'
import { getActionFilterFromFunnelStep, getSignificanceFromBreakdownStep } from './funnelStepTableUtils'
import { cohortsModel } from '~/models/cohortsModel'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { LemonRow } from 'lib/components/LemonRow'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { getSeriesColor } from 'lib/colors'
import { IconFlag } from 'lib/components/icons'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { formatBreakdownLabel } from 'scenes/insights/utils'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { insightLoading, steps, flattenedBreakdowns, hiddenLegendKeys, visibleStepsWithConversionMetrics } =
        useValues(logic)
    const { setHiddenById, toggleVisibilityByBreakdown, openPersonsModalForSeries } = useActions(logic)
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

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
                            rowProps={{ size: 'small', style: { padding: 0, marginLeft: '-0.5rem', font: 'inherit' } }}
                        />
                    ),
                    dataIndex: 'breakdown_value',
                    render: function RenderBreakdownValue(breakdownValue: BreakdownKeyType | undefined): JSX.Element {
                        const label = formatBreakdownLabel(cohorts, formatPropertyValueForDisplay, breakdownValue)
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
                                    size: 'small',
                                    style: { padding: 0, marginLeft: '-0.5rem', maxWidth: '16rem' },
                                    title: label,
                                }}
                            />
                        )
                    },
                },
                {
                    title: (
                        <>
                            Total
                            <br />
                            conversion
                        </>
                    ),
                    render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                        percentage(breakdown?.conversionRates?.total ?? 0, 1, true),
                    align: 'right',
                },
            ],
        },
        ...steps.map((step, stepIndex) => ({
            title: (
                <LemonRow
                    icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                    style={{ font: 'inherit', padding: 0 }}
                    size="small"
                >
                    <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                </LemonRow>
            ),
            children: [
                {
                    title: stepIndex === 0 ? 'Entered' : 'Converted',
                    render: function RenderCompleted(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element | undefined {
                        const stepSeries = breakdown.steps?.[stepIndex]
                        return (
                            stepSeries && (
                                <ValueInspectorButton
                                    onClick={() =>
                                        openPersonsModalForSeries({ step, series: stepSeries, converted: true })
                                    }
                                    style={{ padding: 0 }}
                                >
                                    {humanFriendlyNumber(stepSeries.count ?? 0)}
                                </ValueInspectorButton>
                            )
                        )
                    },

                    align: 'right',
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: 'Dropped off',
                              render: function RenderDropped(
                                  _: void,
                                  breakdown: FlattenedFunnelStepByBreakdown
                              ): JSX.Element | undefined {
                                  const stepSeries = breakdown.steps?.[stepIndex]
                                  return (
                                      stepSeries && (
                                          <ValueInspectorButton
                                              onClick={() =>
                                                  openPersonsModalForSeries({
                                                      step,
                                                      series: stepSeries,
                                                      converted: false,
                                                  })
                                              }
                                              style={{ padding: 0 }}
                                          >
                                              {humanFriendlyNumber(stepSeries.droppedOffFromPrevious ?? 0)}
                                          </ValueInspectorButton>
                                      )
                                  )
                              },
                              align: 'right',
                          },
                      ]),
                {
                    title: (
                        <>
                            Conversion
                            <br />
                            so&nbsp;far
                        </>
                    ),
                    render: function RenderConversionSoFar(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element | string {
                        const significance = getSignificanceFromBreakdownStep(breakdown, step.order)
                        return significance?.total ? (
                            <LemonRow
                                className="significance-highlight"
                                tooltip="Significantly different from other breakdown values"
                                icon={<IconFlag />}
                                size="small"
                            >
                                {percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 1, true)}
                            </LemonRow>
                        ) : (
                            percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 1, true)
                        )
                    },
                    align: 'right',
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: (
                                  <>
                                      Conversion
                                      <br />
                                      from&nbsp;previous
                                  </>
                              ),
                              render: function RenderConversionFromPrevious(
                                  _: void,
                                  breakdown: FlattenedFunnelStepByBreakdown
                              ): JSX.Element | string {
                                  const significance = getSignificanceFromBreakdownStep(breakdown, step.order)
                                  // Only flag as significant here if not flagged already in "Conversion so far"
                                  return !significance?.total && significance?.fromPrevious ? (
                                      <LemonRow
                                          className="significance-highlight"
                                          tooltip="Significantly different from other breakdown values"
                                          icon={<IconFlag />}
                                          size="small"
                                      >
                                          {percentage(
                                              breakdown.steps?.[step.order]?.conversionRates.fromPrevious ?? 0,
                                              1,
                                              true
                                          )}
                                      </LemonRow>
                                  ) : (
                                      percentage(
                                          breakdown.steps?.[step.order]?.conversionRates.fromPrevious ?? 0,
                                          1,
                                          true
                                      )
                                  )
                              },
                              align: 'right',
                          },
                          {
                              title: (
                                  <>
                                      Median
                                      <br />
                                      time
                                  </>
                              ),
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.median_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].median_conversion_time, 3)
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'no-wrap',
                          },
                          {
                              title: (
                                  <>
                                      Average
                                      <br />
                                      time
                                  </>
                              ),
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.average_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].average_conversion_time, 3)
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'no-wrap',
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
            rowKey="breakdownIndex"
            rowStatus={(record) => (record.significant ? 'highlighted' : null)}
            rowRibbonColor={(series) => getSeriesColor(series?.breakdownIndex ?? 0)}
        />
    )
}
