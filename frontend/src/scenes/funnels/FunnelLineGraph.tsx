import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import {
    ChartParams,
    GraphType,
    GraphDataset,
    EntityTypes,
    FunnelStepWithNestedBreakdown,
    IntervalType,
    InsightModel,
    FunnelsFilterType,
} from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, shortTimeZone } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { buildPeopleUrl } from 'scenes/trends/persons-modal/persons-modal-utils'
import { useValues } from 'kea'
import { funnelDataLogic } from './funnelDataLogic'
import { Noun } from '~/models/groupsModel'
import { FunnelsFilter } from '~/queries/schema'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { isInsightQueryNode } from '~/queries/utils'

export function FunnelLineGraphDataExploration(props: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        steps,
        aggregationTargetLabel,
        incompletenessOffsetFromEnd,
        interval,
        querySource,
        funnelsFilter,
        insightData,
    } = useValues(funnelDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    return (
        <FunnelLineGraphComponent
            steps={steps}
            aggregationTargetLabel={aggregationTargetLabel}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            interval={interval ?? undefined}
            aggregationGroupTypeIndex={querySource.aggregation_group_type_index}
            funnelsFilter={funnelsFilter}
            insightData={insightData}
            filters={queryNodeToFilter(querySource)} // for persons modal
            {...props}
        />
    )
}

export function FunnelLineGraph(props: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const { steps, aggregationTargetLabel, incompletenessOffsetFromEnd, filters } = useValues(funnelLogic(insightProps))

    return (
        <FunnelLineGraphComponent
            steps={steps}
            aggregationTargetLabel={aggregationTargetLabel}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            interval={filters.interval}
            aggregationGroupTypeIndex={filters.aggregation_group_type_index}
            funnelsFilter={filters}
            insightData={insight}
            filters={filters}
            {...props}
        />
    )
}

type FunnelLineGraphComponentProps = Omit<ChartParams, 'filters'> & {
    steps: FunnelStepWithNestedBreakdown[]
    aggregationTargetLabel: Noun
    incompletenessOffsetFromEnd: number
    interval?: IntervalType
    aggregationGroupTypeIndex?: number
    funnelsFilter?: FunnelsFilter | null
    insightData?: Partial<InsightModel> | null
    filters: Partial<FunnelsFilterType>
}

function FunnelLineGraphComponent({
    inSharedMode,
    showPersonsModal = true,
    steps,
    aggregationTargetLabel,
    incompletenessOffsetFromEnd,
    interval,
    aggregationGroupTypeIndex,
    insightData,
    filters,
}: FunnelLineGraphComponentProps): JSX.Element | null {
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
                        getFormattedDate(steps[0].days?.[datum.dataIndex], interval) +
                        ' ' +
                        (insightData?.timezone ? shortTimeZone(insightData.timezone) : 'UTC')
                    )
                },
                renderCount: (count) => {
                    return `${count}%`
                },
            }}
            filters={{ aggregation_axis_format: 'percentage' }}
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

                          const props = {
                              action: { id: index, name: label ?? null, properties: [], type: EntityTypes.ACTIONS },
                              date_from: day ?? '',
                              date_to: day ?? '',
                              filters,
                          }

                          const url = buildPeopleUrl(props)

                          if (url) {
                              openPersonsModal({
                                  url,
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
