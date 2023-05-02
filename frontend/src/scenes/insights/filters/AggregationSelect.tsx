import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { InsightLogicProps } from '~/types'
import { insightLogic } from '../insightLogic'
import { isFunnelsQuery, isInsightQueryNode } from '~/queries/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelsQuery } from '~/queries/schema'
import { isFunnelsFilter } from 'scenes/insights/sharedUtils'

type AggregationSelectProps = {
    insightProps: InsightLogicProps
    className?: string
    hogqlAvailable?: boolean
    value?: string
}

function getHogQLValue(groupIndex?: number, aggregationQuery?: string): string {
    if (groupIndex !== undefined) {
        return `$group_${groupIndex}`
    } else if (aggregationQuery) {
        return aggregationQuery
    } else {
        return UNIQUE_USERS
    }
}

export function AggregationSelectDataExploration({
    insightProps,
    className,
    hogqlAvailable,
}: AggregationSelectProps): JSX.Element | null {
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const value = getHogQLValue(
        querySource.aggregation_group_type_index,
        isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnel_aggregate_by_hogql : undefined
    )

    return (
        <AggregationSelectComponent
            className={className}
            hogqlAvailable={hogqlAvailable}
            value={value}
            onChange={(value) => {
                if (hogqlAvailable) {
                    if (isFunnelsQuery(querySource)) {
                        if (value?.startsWith('$group_')) {
                            const aggregation_group_type_index = parseInt(value.replace('$group_', ''))
                            updateQuerySource({
                                aggregation_group_type_index,
                                funnelsFilter: { ...querySource.funnelsFilter, funnel_aggregate_by_hogql: undefined },
                            } as FunnelsQuery)
                        } else {
                            updateQuerySource({
                                aggregation_group_type_index: undefined,
                                funnelsFilter: { ...querySource.funnelsFilter, funnel_aggregate_by_hogql: value },
                            } as FunnelsQuery)
                        }
                    } else {
                        throw new Error('hogqlAvailable is true but querySource is not a funnel query')
                    }
                } else if (value?.startsWith('$group_')) {
                    const aggregation_group_type_index = parseInt(value.replace('$group_', ''))
                    updateQuerySource({ aggregation_group_type_index })
                } else {
                    updateQuerySource({ aggregation_group_type_index: undefined })
                }
            }}
        />
    )
}

export function AggregationSelect({ insightProps, className, hogqlAvailable }: AggregationSelectProps): JSX.Element {
    const { filters } = useValues(insightLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    const value = getHogQLValue(
        filters.aggregation_group_type_index,
        isFunnelsFilter(filters) ? filters.funnel_aggregate_by_hogql : undefined
    )

    return (
        <AggregationSelectComponent
            className={className}
            value={value}
            hogqlAvailable={hogqlAvailable}
            onChange={(value) => {
                if (hogqlAvailable) {
                    if (isFunnelsFilter(filters)) {
                        if (value?.startsWith('$group_')) {
                            const aggregation_group_type_index = parseInt(value.replace('$group_', ''))
                            setFilters({
                                ...filters,
                                aggregation_group_type_index,
                                funnel_aggregate_by_hogql: undefined,
                            })
                        } else {
                            setFilters({
                                ...filters,
                                aggregation_group_type_index: undefined,
                                funnel_aggregate_by_hogql: value,
                            })
                        }
                    } else {
                        throw new Error('hogqlAvailable is true but querySource is not a funnel query')
                    }
                } else if (value?.startsWith('$group_')) {
                    const aggregation_group_type_index = parseInt(value.replace('$group_', ''))
                    setFilters({ ...filters, aggregation_group_type_index })
                } else {
                    setFilters({ ...filters, aggregation_group_type_index: undefined })
                }
            }}
        />
    )
}

const UNIQUE_USERS = 'person_id'
interface AggregationSelectComponentProps {
    className?: string
    hogqlAvailable?: boolean
    value?: string
    onChange: (value: string | undefined) => void
}

function AggregationSelectComponent({
    className,
    hogqlAvailable,
    onChange,
    value,
}: AggregationSelectComponentProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)

    const optionSections: LemonSelectSection<string>[] = [
        {
            title: 'Event Aggregation',
            options: [
                {
                    value: UNIQUE_USERS,
                    label: 'Unique users',
                },
            ],
        },
    ]

    if (needsUpgradeForGroups || canStartUsingGroups) {
        optionSections[0].footer = <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
    } else {
        groupTypes.forEach((groupType) => {
            optionSections[0].options.push({
                value: `$group_${groupType.group_type_index}`,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    if (hogqlAvailable) {
        optionSections[0].options.push({
            value: `properties.$session_id`,
            label: `Unique sessions`,
        })
    }

    return (
        <LemonSelect
            className={className}
            value={value}
            onChange={(newValue) => {
                if (newValue !== null) {
                    onChange(newValue)
                }
            }}
            data-attr="retention-aggregation-selector"
            dropdownMatchSelectWidth={false}
            options={optionSections}
        />
    )
}
