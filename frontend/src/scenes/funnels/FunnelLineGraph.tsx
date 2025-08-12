import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, shortTimeZone } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { FunnelsActorsQuery, NodeKind, TrendsFilter } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { ChartParams, GraphDataset, GraphType } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'
import { funnelPersonsModalLogic } from './funnelPersonsModalLogic'
import { teamLogic } from 'scenes/teamLogic'

const LineGraphWrapper = ({ inCardView, children }: { inCardView?: boolean; children: JSX.Element }): JSX.Element => {
    if (inCardView) {
        return <>{children}</>
    }

    return <div className="TrendsInsight">{children}</div>
}

export function FunnelLineGraph({
    inCardView,
    inSharedMode,
    showPersonsModal: showPersonsModalProp = true,
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { indexedSteps, aggregationTargetLabel, incompletenessOffsetFromEnd, querySource, interval, insightData } =
        useValues(funnelDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const aggregationGroupTypeIndex = querySource.aggregation_group_type_index

    return (
        <LineGraphWrapper inCardView={inCardView}>
            <LineGraph
                data-attr="trend-line-graph-funnel"
                type={GraphType.Line}
                datasets={indexedSteps as unknown as GraphDataset[] /* TODO: better typing */}
                labels={indexedSteps?.[0]?.labels ?? ([] as string[])}
                isInProgress={incompletenessOffsetFromEnd < 0}
                inSharedMode={!!inSharedMode}
                showPersonsModal={showPersonsModal}
                tooltip={{
                    showHeader: false,
                    hideColorCol: true,
                    renderSeries: (_, datum) => {
                        if (!indexedSteps?.[0]?.days) {
                            return 'Trend'
                        }
                        return (
                            getFormattedDate(indexedSteps[0].days?.[datum.dataIndex], {
                                interval,
                                dateRange: insightData?.resolved_date_range,
                                timezone: insightData?.timezone,
                                weekStartDay,
                            }) +
                            ' ' +
                            (insightData?.timezone ? shortTimeZone(insightData.timezone) : 'UTC')
                        )
                    },
                    renderCount: (count) => {
                        return `${count}%`
                    },
                }}
                trendsFilter={{ aggregationAxisFormat: 'percentage' } as TrendsFilter}
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

                              const title = `${capitalizeFirstLetter(
                                  aggregationTargetLabel.plural
                              )} converted on ${dayjs(label).format('MMMM Do YYYY')}`

                              const query: FunnelsActorsQuery = {
                                  kind: NodeKind.FunnelsActorsQuery,
                                  source: querySource,
                                  funnelTrendsDropOff: false,
                                  includeRecordings: true,
                                  funnelTrendsEntrancePeriodStart: dayjs(day).format('YYYY-MM-DD HH:mm:ss'),
                              }
                              openPersonsModal({
                                  title,
                                  query,
                              })
                          }
                }
            />
        </LineGraphWrapper>
    )
}
