import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { ChartParams, GraphType, GraphDataset } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, shortTimeZone } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { buildPeopleUrl } from 'scenes/trends/persons-modal/persons-modal-utils'
import { useValues } from 'kea'
import { funnelDataLogic } from './funnelDataLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { isInsightQueryNode } from '~/queries/utils'
import { TrendsFilter } from '~/queries/schema'

export function FunnelLineGraph({
    inSharedMode,
    showPersonsModal = true,
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { steps, aggregationTargetLabel, incompletenessOffsetFromEnd, interval, querySource, insightData } =
        useValues(funnelDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const aggregationGroupTypeIndex = querySource.aggregation_group_type_index

    return (
        <LineGraph
            data-attr="trend-line-graph-funnel"
            type={GraphType.Line}
            datasets={steps as unknown as GraphDataset[] /* TODO: better typing */}
            labels={steps?.[0]?.labels ?? ([] as string[])}
            isInProgress={incompletenessOffsetFromEnd < 0}
            inSharedMode={!!inSharedMode}
            showPersonsModal={showPersonsModal}
            tooltip={{
                showHeader: false,
                hideColorCol: true,
                renderSeries: (_, datum) => {
                    if (!steps?.[0]?.days) {
                        return 'Trend'
                    }
                    return (
                        getFormattedDate(steps[0].days?.[datum.dataIndex], interval ?? undefined) +
                        ' ' +
                        (insightData?.timezone ? shortTimeZone(insightData.timezone) : 'UTC')
                    )
                },
                renderCount: (count) => {
                    return `${count}%`
                },
            }}
            trendsFilter={{ aggregation_axis_format: 'percentage' } as TrendsFilter}
            labelGroupType={aggregationGroupTypeIndex ?? 'people'}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                !showPersonsModal
                    ? undefined
                    : (payload) => {
                          const { points, index } = payload
                          const dataset = points.clickedPointNotLine
                              ? points.pointsIntersectingClick[0].dataset
                              : points.pointsIntersectingLine[0].dataset
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          const filters = queryNodeToFilter(querySource) // for persons modal
                          const personsUrl = buildPeopleUrl({
                              filters,
                              date_from: day ?? '',
                              response: insightData,
                          })
                          if (personsUrl) {
                              openPersonsModal({
                                  url: personsUrl,
                                  title: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${dayjs(
                                      label
                                  ).format('MMMM Do YYYY')}`,
                              })
                          }
                      }
            }
        />
    )
}
