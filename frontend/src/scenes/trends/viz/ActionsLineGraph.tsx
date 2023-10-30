import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { useValues } from 'kea'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ChartDisplayType, ChartParams, GraphType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { trendsDataLogic } from '../trendsDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { isInsightVizNode, isLifecycleQuery } from '~/queries/utils'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'

export function ActionsLineGraph({
    inSharedMode = false,
    showPersonsModal = true,
    context,
}: ChartParams): JSX.Element | null {
    const { insightProps, hiddenLegendKeys } = useValues(insightLogic)
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

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={display === ChartDisplayType.ActionsBar || isLifecycle ? GraphType.Bar : GraphType.Line}
            hiddenLegendKeys={hiddenLegendKeys}
            datasets={indexedResults}
            labels={(indexedResults[0] && indexedResults[0].labels) || []}
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
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          if (isLifecycle && query && isInsightVizNode(query) && isLifecycleQuery(query.source)) {
                              const newQuery: DataTableNode = {
                                  kind: NodeKind.DataTableNode,
                                  full: true,
                                  source: {
                                      kind: NodeKind.PersonsQuery,
                                      source: {
                                          kind: NodeKind.InsightPersonsQuery,
                                          source: query.source,
                                          day,
                                          status: dataset.status,
                                      },
                                  },
                              }
                              router.actions.push(combineUrl(urls.persons(), undefined, { q: newQuery }).url)
                              return
                          }

                          if (!dataset) {
                              return
                          }

                          const datasetUrls = urlsForDatasets(crossDataset, index)

                          if (datasetUrls?.length) {
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
                                  urls: datasetUrls,
                                  urlsIndex: crossDataset?.findIndex((x) => x.id === dataset.id) || 0,
                                  title,
                              })
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    )
}
