import { DeepPartial } from 'chart.js/dist/types/utils'
import { useValues } from 'kea'

import { Chart, ChartType, LegendOptions, defaults } from 'lib/Chart'
import { ForecastBand, insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
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

    const { alertThresholdLines, forecastBands } = useValues(
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

    // Helper to create forecast band datasets from ForecastBand
    const createForecastBandDatasets = (
        forecastBand: ForecastBand,
        seriesIndex: number,
        seriesLabel: string,
        seriesColor: string
    ): {
        lower: Record<string, unknown>
        upper: Record<string, unknown>
        predicted: Record<string, unknown>
    } | null => {
        // Map forecast timestamps to label indices
        const forecastDataLower: (number | null)[] = new Array(labels.length).fill(null)
        const forecastDataUpper: (number | null)[] = new Array(labels.length).fill(null)
        const forecastDataPredicted: (number | null)[] = new Array(labels.length).fill(null)

        for (let i = 0; i < forecastBand.timestamps.length; i++) {
            const timestamp = forecastBand.timestamps[i]
            // Find the matching label index
            const labelIndex = labels.findIndex((label) => {
                // Normalize both dates to ISO strings for comparison
                // This handles timezone differences and various input formats
                const normalizeToISO = (dateStr: string): string => {
                    // Handle date-only strings (YYYY-MM-DD) by treating them as UTC
                    // JS Date() parses these as local time, but backend stores as UTC
                    let normalized = dateStr
                    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
                        normalized = `${dateStr}T00:00:00Z`
                    }
                    const d = new Date(normalized)
                    // Return ISO string without milliseconds for consistent comparison
                    return d.toISOString().split('.')[0]
                }
                return normalizeToISO(label) === normalizeToISO(timestamp)
            })

            if (labelIndex !== -1) {
                forecastDataLower[labelIndex] = forecastBand.lowerBounds[i]
                forecastDataUpper[labelIndex] = forecastBand.upperBounds[i]
                forecastDataPredicted[labelIndex] = forecastBand.predictedValues[i]
            }
        }

        // Only add if we have some forecast data that maps to labels
        if (forecastDataLower.every((v) => v === null)) {
            return null
        }

        const yAxisID = showMultipleYAxes && seriesIndex > 0 ? `y${seriesIndex}` : 'y'

        return {
            lower: {
                label: `${seriesLabel} - lower bound`,
                data: forecastDataLower,
                borderColor: seriesColor,
                backgroundColor: 'transparent',
                pointRadius: 0,
                borderWidth: 0,
                hideTooltip: false,
                yAxisID,
            },
            upper: {
                label: `${seriesLabel} - upper bound`,
                data: forecastDataUpper,
                borderColor: seriesColor,
                backgroundColor: hexToRGBA(seriesColor, 0.1),
                pointRadius: 0,
                borderWidth: 0,
                fill: '-1',
                hideTooltip: false,
                yAxisID,
            },
            predicted: {
                label: `${seriesLabel} - predicted`,
                data: forecastDataPredicted,
                borderColor: seriesColor,
                backgroundColor: 'transparent',
                pointRadius: 0,
                borderWidth: 2,
                borderDash: [5, 5],
                hideTooltip: false,
                yAxisID,
            },
        }
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

        // Add forecast bands for this series
        if (forecastBands && forecastBands.length > 0) {
            const seriesLabel = originalDataset.label || `Series ${index}`
            for (const band of forecastBands) {
                const bandDatasets = createForecastBandDatasets(band, index, seriesLabel, color)
                if (bandDatasets) {
                    // Cast to any as these are synthetic datasets for visualization only
                    datasets.push(bandDatasets.lower as any, bandDatasets.upper as any, bandDatasets.predicted as any)
                }
            }
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
