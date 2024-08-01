import { ChartType, defaults, LegendOptions } from 'chart.js'
import { DeepPartial } from 'chart.js/dist/types/utils'
import { useValues } from 'kea'
import { Chart } from 'lib/Chart'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
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
    const { insightProps } = useValues(insightLogic)
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
        isLifecycle,
        isStickiness,
        isDataWarehouseSeries,
        showLegend,
        hiddenLegendIndexes,
        querySource,
        yAxisScaleType,
    } = useValues(trendsDataLogic(insightProps))

    const labels =
        (indexedResults.length === 2 &&
            indexedResults.every((x) => x.compare) &&
            indexedResults.find((x) => x.compare_label === 'current')?.days) ||
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

    return (
        <LineGraph
            data-attr="trend-line-graph"
            type={display === ChartDisplayType.ActionsBar || isLifecycle ? GraphType.Bar : GraphType.Line}
            hiddenLegendIndexes={hiddenLegendIndexes}
            datasets={indexedResults}
            labels={labels}
            inSharedMode={inSharedMode}
            labelGroupType={labelGroupType}
            showPersonsModal={showPersonsModal}
            trendsFilter={trendsFilter}
            formula={formula}
            showValuesOnSeries={showValuesOnSeries}
            showPercentStackView={showPercentStackView}
            supportsPercentStackView={supportsPercentStackView}
            yAxisScaleType={yAxisScaleType}
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
                    : undefined
            }
            isInProgress={!isStickiness && incompletenessOffsetFromEnd < 0}
            isArea={display === ChartDisplayType.ActionsAreaGraph}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            legend={legend}
            onClick={
                !showPersonsModal || isMultiSeriesFormula(formula) || isDataWarehouseSeries
                    ? undefined
                    : (payload) => {
                          const { index, points } = payload

                          const dataset = points.referencePoint.dataset
                          if (!dataset) {
                              return
                          }

                          const day = dataset.action?.days?.[index] ?? dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          const title = isStickiness ? (
                              <>
                                  <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on day {day}
                              </>
                          ) : (
                              (label: string) => (
                                  <>
                                      {label} on{' '}
                                      <DateDisplay interval={interval || 'day'} date={day?.toString() || ''} />
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
            }
        />
    )
}
