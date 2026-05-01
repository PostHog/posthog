import { useValues } from 'kea'

import { DateDisplay } from 'lib/components/DateDisplay'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, shortTimeZone } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FunnelsActorsQuery, NodeKind, TrendsFilter } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { BreakdownKeyType, ChartParams, GraphDataset, GraphType } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'
import { funnelPersonsModalLogic } from './funnelPersonsModalLogic'

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
    const {
        indexedSteps,
        goalLines,
        aggregationTargetLabel,
        incompletenessOffsetFromEnd,
        querySource,
        interval,
        insightData,
        showValuesOnSeries,
        funnelsFilter,
        breakdownFilter,
        labelGroupType,
    } = useValues(funnelDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const showPersonsModal = canOpenPersonModal && showPersonsModalProp

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
                showValuesOnSeries={showValuesOnSeries}
                showTrendLines={funnelsFilter?.showTrendLines ?? false}
                goalLines={goalLines ?? []}
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
                labelGroupType={labelGroupType}
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
                              const breakdownValue = (dataset as { breakdown_value?: BreakdownKeyType })
                                  ?.breakdown_value
                              const hasBreakdown =
                                  breakdownValue !== undefined &&
                                  breakdownValue !== 'Baseline' &&
                                  !(Array.isArray(breakdownValue) && breakdownValue[0] === 'Baseline')
                              const breakdownLabel = hasBreakdown
                                  ? formatBreakdownLabel(
                                        breakdownValue,
                                        breakdownFilter,
                                        allCohorts.results,
                                        formatPropertyValueForDisplay
                                    )
                                  : null

                              const title = (
                                  <>
                                      {capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on{' '}
                                      <DateDisplay
                                          interval={interval || 'day'}
                                          resolvedDateRange={insightData?.resolved_date_range}
                                          timezone={timezone}
                                          weekStartDay={weekStartDay}
                                          date={day?.toString() || ''}
                                      />
                                      {breakdownLabel ? <> • {breakdownLabel}</> : null}
                                  </>
                              )

                              const query: FunnelsActorsQuery = {
                                  kind: NodeKind.FunnelsActorsQuery,
                                  source: querySource,
                                  funnelTrendsDropOff: false,
                                  includeRecordings: true,
                                  funnelTrendsEntrancePeriodStart: dayjs(day).format('YYYY-MM-DD HH:mm:ss'),
                                  ...(hasBreakdown ? { funnelStepBreakdown: breakdownValue } : {}),
                              }
                              openPersonsModal({
                                  title,
                                  query,
                              })
                          }
                }
                hideAnnotations={inSharedMode}
            />
        </LineGraphWrapper>
    )
}
