import { useValues } from 'kea'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { NodeKind } from '~/queries/schema'
import { isInsightVizNode, isLifecycleQuery } from '~/queries/utils'
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
    const { query } = useValues(insightDataLogic(insightProps))
    const {
        indexedResults,
        labelGroupType,
        incompletenessOffsetFromEnd,
        formula,
        compare,
        display,
        interval,
        showValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        trendsFilter,
        isLifecycle,
        isStickiness,
    } = useValues(trendsDataLogic(insightProps))

    const labels =
        (indexedResults.length === 2 &&
            indexedResults.every((x) => x.compare) &&
            indexedResults.find((x) => x.compare_label === 'current')?.days) ||
        (indexedResults[0] && indexedResults[0].labels) ||
        []

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
            showValueOnSeries={showValueOnSeries}
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
                              return capitalizeFirstLetter(datum.label?.split(' - ')?.[1] ?? datum.label ?? 'None')
                          },
                      }
                    : undefined
            }
            compare={compare}
            isInProgress={!isStickiness && incompletenessOffsetFromEnd < 0}
            isArea={display === ChartDisplayType.ActionsAreaGraph}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                !showPersonsModal || isMultiSeriesFormula(formula)
                    ? undefined
                    : (payload) => {
                          const { index, points, crossDataset } = payload

                          const dataset = points.referencePoint.dataset
                          if (!dataset) {
                              return
                          }

                          const day = dataset?.days?.[index] ?? ''
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
                              featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_LIFECYCLE] &&
                              isLifecycle &&
                              query &&
                              isInsightVizNode(query) &&
                              isLifecycleQuery(query.source)
                          ) {
                              openPersonsModal({
                                  title,
                                  query: {
                                      kind: NodeKind.InsightPersonsQuery,
                                      source: query.source,
                                      day,
                                      status: dataset.status,
                                  },
                              })
                          } else {
                              const datasetUrls = urlsForDatasets(crossDataset, index)
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
