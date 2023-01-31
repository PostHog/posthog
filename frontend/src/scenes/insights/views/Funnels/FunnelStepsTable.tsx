import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/lemon-ui/LemonTable'
import { FlattenedFunnelStepByBreakdown } from '~/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getVisibilityKey } from 'scenes/funnels/funnelUtils'
import { getActionFilterFromFunnelStep, getSignificanceFromBreakdownStep } from './funnelStepTableUtils'
import { cohortsModel } from '~/models/cohortsModel'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { getSeriesColor } from 'lib/colors'
import { IconFlag } from 'lib/lemon-ui/icons'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { formatBreakdownLabel } from 'scenes/insights/utils'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        insightLoading,
        filters,
        steps,
        flattenedBreakdowns,
        hiddenLegendKeys,
        visibleStepsWithConversionMetrics,
        isOnlySeries,
    } = useValues(logic)
    const { setHiddenById, toggleVisibilityByBreakdown, openPersonsModalForSeries } = useActions(logic)
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const allChecked = flattenedBreakdowns?.every((b) => !hiddenLegendKeys[getVisibilityKey(b.breakdown_value)])

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
                                    (b) => !hiddenLegendKeys[getVisibilityKey(b.breakdown_value)]
                                )
                                    ? 'indeterminate'
                                    : false)
                            }
                            onChange={() => {
                                // Either toggle all data on or off
                                setHiddenById(
                                    Object.fromEntries(
                                        visibleStepsWithConversionMetrics.flatMap(() =>
                                            flattenedBreakdowns.map((b) => [
                                                getVisibilityKey(b.breakdown_value),
                                                allChecked,
                                            ])
                                        )
                                    )
                                )
                            }}
                            label={<span className="font-bold">Breakdown</span>}
                            size="small"
                        />
                    ),
                    dataIndex: 'breakdown_value',
                    render: function RenderBreakdownValue(
                        _: void,
                        breakdown: FlattenedFunnelStepByBreakdown
                    ): JSX.Element {
                        // :KLUDGE: `BreakdownStepValues` is always wrapped into an array, which doesn't work for the
                        // formatBreakdownLabel logic. Instead, we unwrap speculatively
                        const value =
                            breakdown.breakdown_value?.length == 1
                                ? breakdown.breakdown_value[0]
                                : breakdown.breakdown_value
                        const label = formatBreakdownLabel(
                            cohorts,
                            formatPropertyValueForDisplay,
                            value,
                            breakdown.breakdown,
                            filters.breakdown_type
                        )
                        return isOnlySeries ? (
                            <span className="font-medium">{label}</span>
                        ) : (
                            <LemonCheckbox
                                checked={!hiddenLegendKeys[getVisibilityKey(breakdown.breakdown_value)]}
                                onChange={() => toggleVisibilityByBreakdown(breakdown.breakdown_value)}
                                label={label}
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
                        percentage(breakdown?.conversionRates?.total ?? 0, 2, true),
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
                                {percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 2, true)}
                            </LemonRow>
                        ) : (
                            percentage(breakdown.steps?.[step.order]?.conversionRates.total ?? 0, 2, true)
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
                                              2,
                                              true
                                          )}
                                      </LemonRow>
                                  ) : (
                                      percentage(
                                          breakdown.steps?.[step.order]?.conversionRates.fromPrevious ?? 0,
                                          2,
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
                              className: 'whitespace-nowrap',
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
                              className: 'whitespace-nowrap',
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
