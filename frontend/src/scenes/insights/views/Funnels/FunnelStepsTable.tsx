import { useActions, useValues } from 'kea'
import { compare as compareFn } from 'natural-orderby'

import { IconFlag } from '@posthog/icons'
import { LemonColorButton } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonTable, LemonTableColumn, LemonTableColumnGroup } from 'lib/lemon-ui/LemonTable'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { getVisibilityKey } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { resultCustomizationsModalLogic } from '../../../../queries/nodes/InsightViz/resultCustomizationsModalLogic'
import { getActionFilterFromFunnelStep, getSignificanceFromBreakdownStep } from './funnelStepTableUtils'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps, insightLoading, editingDisabledReason } = useValues(insightLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { steps, flattenedBreakdowns, hiddenLegendBreakdowns, getFunnelsColor, isStepOptional } = useValues(
        funnelDataLogic(insightProps)
    )
    const { setHiddenLegendBreakdowns, toggleLegendBreakdownVisibility, setBreakdownSortOrder } = useActions(
        funnelDataLogic(insightProps)
    )
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    const isOnlySeries = flattenedBreakdowns.length <= 1

    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const allChecked = flattenedBreakdowns?.every(
        (b) => !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
    )
    const someChecked = flattenedBreakdowns?.some(
        (b) => !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
    )

    /** :HACKY: We don't want to allow changing of colors in experiments (they can't be
    saved there). Therefore we use the `disable_baseline` prop on the cached insight passed
    in by experiments as a measure of detecting wether we are in an experiment context.
    Likely this can be done in a better way once experiments are re-written to use their own
    queries. */
    const showCustomizationIcon = !insightProps.cachedInsight?.disable_baseline

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
                            disabledReason={editingDisabledReason}
                        />
                    ),
                    dataIndex: 'breakdown_value',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) => {
                        // Unwrap breakdown values to compare them properly
                        const valueA = a.breakdown_value?.length == 1 ? a.breakdown_value[0] : a.breakdown_value
                        const valueB = b.breakdown_value?.length == 1 ? b.breakdown_value[0] : b.breakdown_value

                        // For numeric values, use numeric comparison
                        if (typeof valueA === 'number' && typeof valueB === 'number') {
                            return valueA - valueB
                        }

                        // For string values, use string comparison
                        const labelA = formatBreakdownLabel(
                            valueA,
                            breakdownFilter,
                            allCohorts.results,
                            formatPropertyValueForDisplay
                        )
                        const labelB = formatBreakdownLabel(
                            valueB,
                            breakdownFilter,
                            allCohorts.results,
                            formatPropertyValueForDisplay
                        )
                        return compareFn()(labelA, labelB)
                    },
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

                        const color = getFunnelsColor(breakdown)

                        const label = (
                            <div className="flex justify-between items-center">
                                {formatBreakdownLabel(
                                    value,
                                    breakdownFilter,
                                    allCohorts.results,
                                    formatPropertyValueForDisplay
                                )}
                                {showCustomizationIcon && (
                                    <LemonColorButton
                                        onClick={() => openModal(breakdown)}
                                        color={color}
                                        type="tertiary"
                                        size="small"
                                        disabledReason={editingDisabledReason}
                                    />
                                )}
                            </div>
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
                                disabledReason={editingDisabledReason}
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
                    key: 'total_conversion',
                    render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                        percentage(breakdown?.conversionRates?.total ?? 0, 2, true),
                    align: 'right',
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a?.conversionRates?.total ?? 0) - (b?.conversionRates?.total ?? 0),
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
                    <EntityFilterInfo
                        filter={getActionFilterFromFunnelStep(step)}
                        isOptional={isStepOptional(stepIndex + 1)}
                    />
                </LemonRow>
            ),
            children: [
                {
                    title: stepIndex === 0 ? 'Entered' : 'Converted',
                    key: `step_${stepIndex}_conversion`,
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
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a.steps?.[stepIndex]?.count ?? 0) - (b.steps?.[stepIndex]?.count ?? 0),
                },
                ...(stepIndex === 0
                    ? []
                    : [
                          {
                              title: 'Dropped off',
                              key: `step_${stepIndex}_dropoff`,
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
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[stepIndex]?.droppedOffFromPrevious ?? 0) -
                                  (b.steps?.[stepIndex]?.droppedOffFromPrevious ?? 0),
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
                    key: `step_${stepIndex}_conversion_so_far`,
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
                    sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                        (a.steps?.[step.order]?.conversionRates.total ?? 0) -
                        (b.steps?.[step.order]?.conversionRates.total ?? 0),
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
                              key: `step_${stepIndex}_conversion_from_prev`,
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
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.conversionRates.fromPrevious ?? 0) -
                                  (b.steps?.[step.order]?.conversionRates.fromPrevious ?? 0),
                          },
                          {
                              title: (
                                  <>
                                      Median
                                      <br />
                                      time
                                  </>
                              ),
                              key: `step_${stepIndex}_median_time`,
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.median_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].median_conversion_time, {
                                            maxUnits: 3,
                                        })
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'whitespace-nowrap',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.median_conversion_time ?? 0) -
                                  (b.steps?.[step.order]?.median_conversion_time ?? 0),
                          },
                          {
                              title: (
                                  <>
                                      Average
                                      <br />
                                      time
                                  </>
                              ),
                              key: `step_${stepIndex}_average_time`,
                              render: (_: void, breakdown: FlattenedFunnelStepByBreakdown) =>
                                  breakdown.steps?.[step.order]?.average_conversion_time != undefined
                                      ? humanFriendlyDuration(breakdown.steps[step.order].average_conversion_time, {
                                            maxUnits: 3,
                                        })
                                      : '–',
                              align: 'right',
                              width: 0,
                              className: 'whitespace-nowrap',
                              sorter: (a: FlattenedFunnelStepByBreakdown, b: FlattenedFunnelStepByBreakdown) =>
                                  (a.steps?.[step.order]?.average_conversion_time ?? 0) -
                                  (b.steps?.[step.order]?.average_conversion_time ?? 0),
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
            rowRibbonColor={getFunnelsColor}
            firstColumnSticky
            useURLForSorting
            onSort={(newSorting) => {
                if (!newSorting) {
                    return
                }
                // Find the column definition by key
                const findColumnByKey = (
                    columns: LemonTableColumnGroup<FlattenedFunnelStepByBreakdown>[],
                    key: string
                ): LemonTableColumn<
                    FlattenedFunnelStepByBreakdown,
                    keyof FlattenedFunnelStepByBreakdown | undefined
                > | null => {
                    for (const group of columns) {
                        for (const col of group.children) {
                            if (col.key === key || col.dataIndex === key) {
                                return col
                            }
                        }
                    }
                    return null
                }
                const column = findColumnByKey(columnsGrouped, newSorting.columnKey)
                const sorter = column?.sorter
                if (typeof sorter === 'function') {
                    const sorted = [...flattenedBreakdowns].sort((a, b) => newSorting.order * sorter(a, b))
                    setBreakdownSortOrder(
                        sorted
                            .flatMap((b) => b.breakdown_value ?? [])
                            .filter((v): v is string | number => v !== undefined)
                    )
                }
            }}
        />
    )
}
