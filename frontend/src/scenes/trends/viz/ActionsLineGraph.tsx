import { DeepPartial } from 'chart.js/dist/types/utils'
import { useValues } from 'kea'

import { Chart, ChartType, LegendOptions, defaults } from 'lib/Chart'
import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ciRanges, movingAverage } from 'lib/statistics'
import { capitalizeFirstLetter, hexToRGBA, isMultiSeriesFormula } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { ChartDisplayType, ChartParams, GraphType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'

export function ActionsLineGraph({
    inSharedMode = false,
    showPersonsModal = true,
    context,
}: ChartParams): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedResults,
        labelGroupType,
        incompletenessOffsetFromEnd,
        formula,
        display,
        interval,
        showValuesOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        trendsFilter,
        lifecycleFilter,
        isLifecycle,
        isStickiness,
        hasDataWarehouseSeries,
        showLegend,
        querySource,
        yAxisScaleType,
        showMultipleYAxes,
        goalLines,
        insightData,
        showConfidenceIntervals,
        confidenceLevel,
        showTrendLines,
        showMovingAverage,
        movingAverageIntervals,
        getTrendsColor,
    } = useValues(trendsDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)

    const { alertThresholdLines } = useValues(
        insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    )

    const labels =
        (indexedResults.length === 2 &&
            indexedResults.every((x) => x.compare) &&
            indexedResults.find((x) => x.compare_label === 'current')?.labels) ||
        (indexedResults[0] && indexedResults[0].labels) ||
        []

    const shortenLifecycleLabels = (s: string | undefined): string =>
        capitalizeFirstLetter(s?.split(' - ')?.[1] ?? s ?? 'None')

    const legend: DeepPartial<LegendOptions<ChartType>> = {
        display: false,
    }
    if (isLifecycle && !!showLegend) {
        legend.display = true
        legend.labels = {
            generateLabels: (chart: Chart) => {
                const labelElements = defaults.plugins.legend.labels.generateLabels(chart)
                labelElements.forEach((elt) => {
                    elt.text = shortenLifecycleLabels(elt.text)
                })
                return labelElements
            },
        }
    }

    if (
        !(indexedResults && indexedResults[0]?.data && indexedResults.filter((result) => result.count !== 0).length > 0)
    ) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    const finalDatasets = indexedResults.flatMap((originalDataset, index) => {
        const yAxisID = showMultipleYAxes && index > 0 ? `y${index}` : 'y'
        const mainSeries = { ...originalDataset, yAxisID }
        const datasets = [mainSeries]
        const color = getTrendsColor(originalDataset)

        if (showConfidenceIntervals) {
            const [lower, upper] = ciRanges(originalDataset.data, confidenceLevel / 100)

            const lowerCIBound = {
                ...originalDataset,
                label: `${originalDataset.label} (CI lower)`,
                action: {
                    ...originalDataset.action,
                    name: `${originalDataset.label} (CI lower)`,
                },
                data: lower,
                borderColor: color,
                backgroundColor: 'transparent',
                pointRadius: 0,
                borderWidth: 0,
                hideTooltip: true,
                yAxisID,
            }
            const upperCIBound = {
                ...originalDataset,
                label: `${originalDataset.label} (CI upper)`,
                action: {
                    ...originalDataset.action,
                    name: `${originalDataset.label} (CI upper)`,
                },
                data: upper,
                borderColor: color,
                backgroundColor: hexToRGBA(color, 0.2),
                pointRadius: 0,
                borderWidth: 0,
                fill: '-1',
                hideTooltip: true,
                yAxisID,
            }
            datasets.push(lowerCIBound, upperCIBound)
        }

        if (showMovingAverage) {
            const movingAverageData = movingAverage(originalDataset.data, movingAverageIntervals)
            const movingAverageDataset = {
                ...originalDataset,
                label: `${originalDataset.label} (Moving avg)`,
                action: {
                    ...originalDataset.action,
                    name: `${originalDataset.label} (Moving avg)`,
                },
                data: movingAverageData,
                borderColor: color,
                backgroundColor: 'transparent',
                pointRadius: 0,
                borderWidth: 2,
                borderDash: [10, 3],
                hideTooltip: true,
                yAxisID,
            }
            datasets.push(movingAverageDataset)
        }
        return datasets
    })

    return (
        <LineGraph
            data-attr="trend-line-graph"
            type={
                display === ChartDisplayType.ActionsBar ||
                display === ChartDisplayType.ActionsUnstackedBar ||
                isLifecycle
                    ? GraphType.Bar
                    : GraphType.Line
            }
            datasets={finalDatasets}
            labels={labels}
            inSharedMode={inSharedMode}
            labelGroupType={labelGroupType}
            showPersonsModal={showPersonsModal}
            trendsFilter={trendsFilter}
            formula={formula}
            showValuesOnSeries={showValuesOnSeries}
            showPercentView={isStickiness}
            showPercentStackView={showPercentStackView}
            supportsPercentStackView={supportsPercentStackView}
            isStacked={
                isLifecycle ? (lifecycleFilter?.stacked ?? true) : display !== ChartDisplayType.ActionsUnstackedBar
            }
            yAxisScaleType={yAxisScaleType}
            showMultipleYAxes={showMultipleYAxes}
            showTrendLines={showTrendLines}
            tooltip={
                isLifecycle
                    ? {
                          altTitle: 'Users',
                          altRightTitle: (_, date) => {
                              return date
                          },
                          renderSeries: (_, datum) => {
                              return shortenLifecycleLabels(datum.label)
                          },
                      }
                    : {
                          groupTypeLabel: context?.groupTypeLabel,
                          filter: (s) => !s.hideTooltip,
                      }
            }
            isInProgress={!isStickiness && incompletenessOffsetFromEnd < 0}
            isArea={display === ChartDisplayType.ActionsAreaGraph}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            legend={legend}
            hideAnnotations={inSharedMode}
            goalLines={[...alertThresholdLines, ...(goalLines || [])]}
            onClick={
                context?.onDataPointClick ||
                (showPersonsModal && !isMultiSeriesFormula(formula) && !hasDataWarehouseSeries)
                    ? (payload) => {
                          const { index, points } = payload

                          const dataset = points.referencePoint.dataset
                          if (!dataset) {
                              return
                          }

                          const day = dataset.action?.days?.[index] ?? dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          if (context?.onDataPointClick) {
                              context.onDataPointClick(
                                  {
                                      breakdown: dataset.breakdownValues?.[index],
                                      compare: dataset.compareLabels?.[index] || undefined,
                                      day,
                                  },
                                  indexedResults[0]
                              )
                              return
                          }

                          const title = isStickiness ? (
                              <>
                                  <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on{' '}
                                  {interval || 'day'} {day}
                              </>
                          ) : (
                              (label: string) => (
                                  <>
                                      {label} on{' '}
                                      <DateDisplay
                                          interval={interval || 'day'}
                                          resolvedDateRange={insightData?.resolved_date_range}
                                          timezone={timezone}
                                          weekStartDay={weekStartDay}
                                          date={day?.toString() || ''}
                                      />
                                  </>
                              )
                          )

                          openPersonsModal({
                              title,
                              query: datasetToActorsQuery({ dataset, query: querySource!, day }),
                              additionalSelect:
                                  isLifecycle || isStickiness
                                      ? {}
                                      : {
                                            value_at_data_point: 'event_count',
                                            matched_recordings: 'matched_recordings',
                                        },
                              orderBy: isLifecycle || isStickiness ? undefined : ['event_count DESC, actor_id DESC'],
                          })
                      }
                    : undefined
            }
        />
    )
}
