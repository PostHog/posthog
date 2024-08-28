import { IconFlag } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/lemon-ui/LemonTable'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { getVisibilityKey } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { getActionFilterFromFunnelStep, getSignificanceFromBreakdownStep } from './funnelStepTableUtils'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { steps, flattenedBreakdowns, hiddenLegendBreakdowns } = useValues(funnelDataLogic(insightProps))
    const { setHiddenLegendBreakdowns, toggleLegendBreakdownVisibility } = useActions(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))

    const isOnlySeries = flattenedBreakdowns.length <= 1

    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const allChecked = flattenedBreakdowns?.every(
        (b) => !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
    )
    const someChecked = flattenedBreakdowns?.some(
        (b) => !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
    )

    const columnsGrouped = [
        {
            children: [
                {
                    title: isOnlySeries ? (
                        'Breakdown'
                    ) : (
                        <LemonCheckbox
                            checked={allChecked ? true : someChecked ? 'indeterminate' : false}
                            onChange={() => {
                                // Either toggle all breakdowns on or off
                                setHiddenLegendBreakdowns(
                                    allChecked
                                        ? flattenedBreakdowns.map((b) => getVisibilityKey(b.breakdown_value))
                                        : []
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
                            value,
                            breakdownFilter,
                            cohorts,
                            formatPropertyValueForDisplay
                        )
                        return isOnlySeries ? (
                            <span className="font-medium">{label}</span>
                        ) : (
                            <LemonCheckbox
                                checked={!hiddenLegendBreakdowns?.includes(getVisibilityKey(breakdown.breakdown_value))}
                                onChange={() =>
                                    toggleLegendBreakdownVisibility(getVisibilityKey(breakdown.breakdown_value))
                                }
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
                            stepSeries &&
                            (canOpenPersonModal ? (
                                <ValueInspectorButton
                                    onClick={() =>
                                        openPersonsModalForSeries({ step, series: stepSeries, converted: true })
                                    }
                                >
                                    {humanFriendlyNumber(stepSeries.count ?? 0)}
                                </ValueInspectorButton>
                            ) : (
                                <>{humanFriendlyNumber(stepSeries.count ?? 0)}</>
                            ))
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
                                      stepSeries &&
                                      (canOpenPersonModal ? (
                                          <ValueInspectorButton
                                              onClick={() =>
                                                  openPersonsModalForSeries({
                                                      step,
                                                      series: stepSeries,
                                                      converted: false,
                                                  })
                                              }
                                          >
                                              {humanFriendlyNumber(stepSeries.droppedOffFromPrevious ?? 0)}
                                          </ValueInspectorButton>
                                      ) : (
                                          <>{humanFriendlyNumber(stepSeries.droppedOffFromPrevious ?? 0)}</>
                                      ))
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
                                className="funnel-significance-highlight"
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
                                          className="funnel-significance-highlight"
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
            firstColumnSticky
        />
    )
}
