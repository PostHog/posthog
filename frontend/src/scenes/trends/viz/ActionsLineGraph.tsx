import { ChartType, defaults, LegendOptions } from 'chart.js'
import { _DeepPartialObject } from 'chart.js/types/utils'
import { useValues } from 'kea'
import { Chart } from 'lib/Chart'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { isInsightVizNode, isLifecycleQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, ChartParams, GraphType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'

export function ActionsLineGraph({
    inSharedMode = false,
    showPersonsModal = true,
    context,
}: ChartParams): JSX.Element | null {
    const { insightProps, hiddenLegendKeys } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { query } = useValues(insightDataLogic(insightProps))
    const {
        indexedResults,
        labelGroupType,
        incompletenessOffsetFromEnd,
        formula,
        compare,
        display,
        interval,
        showValuesOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        trendsFilter,
        isLifecycle,
        isStickiness,
        isTrends,
        isDataWarehouseSeries,
        showLegend,
    } = useValues(trendsDataLogic(insightProps))

    const labels =
        (indexedResults.length === 2 &&
            indexedResults.every((x) => x.compare) &&
            indexedResults.find((x) => x.compare_label === 'current')?.days) ||
        (indexedResults[0] && indexedResults[0].labels) ||
        []

    const isLifecycleQueryWithFeatureFlagOn =
        (featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS] || featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_LIFECYCLE]) &&
        isLifecycle &&
        query &&
        isInsightVizNode(query) &&
        isLifecycleQuery(query.source)

    const isStickinessQueryWithFeatureFlagOn =
        (featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS] || featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_STICKINESS]) &&
        isStickiness &&
        query &&
        isInsightVizNode(query) &&
        isStickinessQuery(query.source)

    const isTrendsQueryWithFeatureFlagOn =
        (featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS] || featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_TRENDS]) &&
        isTrends &&
        query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source)

    const shortenLifecycleLabels = (s: string | undefined): string =>
        capitalizeFirstLetter(s?.split(' - ')?.[1] ?? s ?? 'None')

    const legend: _DeepPartialObject<LegendOptions<ChartType>> = {
        display: !!showLegend,
    }
    if (isLifecycle) {
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

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={display === ChartDisplayType.ActionsBar || isLifecycle ? GraphType.Bar : GraphType.Line}
            hiddenLegendKeys={hiddenLegendKeys}
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
            compare={compare}
            isInProgress={!isStickiness && incompletenessOffsetFromEnd < 0}
            isArea={display === ChartDisplayType.ActionsAreaGraph}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            legend={legend}
            onClick={
                !showPersonsModal || isMultiSeriesFormula(formula) || isDataWarehouseSeries
                    ? undefined
                    : (payload) => {
                          const { index, points, crossDataset } = payload

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

                          if (
                              isLifecycleQueryWithFeatureFlagOn ||
                              isStickinessQueryWithFeatureFlagOn ||
                              isTrendsQueryWithFeatureFlagOn
                          ) {
                              openPersonsModal({
                                  title,
                                  query: datasetToActorsQuery({ dataset, query: query.source, day }),
                                  additionalSelect: isLifecycle
                                      ? {}
                                      : {
                                            value_at_data_point: 'event_count',
                                            matched_recordings: 'matched_recordings',
                                        },
                              })
                          } else {
                              const datasetUrls = urlsForDatasets(
                                  crossDataset,
                                  index,
                                  cohorts,
                                  formatPropertyValueForDisplay
                              )
                              if (datasetUrls?.length) {
                                  openPersonsModal({
                                      urls: datasetUrls,
                                      urlsIndex: crossDataset?.findIndex((x) => x.id === dataset.id) || 0,
                                      title,
                                  })
                              }
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    )
}
