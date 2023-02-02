import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { InsightLogicProps } from '~/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

type AggregationSelectProps = {
    insightProps: InsightLogicProps
}

export function AggregationSelectDataExploration({ insightProps }: AggregationSelectProps): JSX.Element {
    const { querySource } = useValues(funnelDataLogic(insightProps))
    const { updateQuerySource } = useActions(funnelDataLogic(insightProps))

    return (
        <AggregationSelectComponent
            aggregationGroupTypeIndex={querySource.aggregation_group_type_index}
            onChange={(aggregation_group_type_index) => updateQuerySource({ aggregation_group_type_index })}
        />
    )
}

export function AggregationSelect({ insightProps }: AggregationSelectProps): JSX.Element {
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    return (
        <AggregationSelectComponent
            aggregationGroupTypeIndex={filters.aggregation_group_type_index}
            onChange={(aggregation_group_type_index) => setFilters({ aggregation_group_type_index })}
        />
    )
}

const UNIQUE_USERS = -1
interface AggregationSelectComponentProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregation_group_type_index: number | undefined) => void
}

export function AggregationSelectComponent({
    aggregationGroupTypeIndex: aggregation_group_type_index,
    onChange,
}: AggregationSelectComponentProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)

    const optionSections: LemonSelectSection<number>[] = [
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
                value: groupType.group_type_index,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    return (
        <LemonSelect
            value={aggregation_group_type_index === undefined ? UNIQUE_USERS : aggregation_group_type_index}
            onChange={(value) => {
                if (value !== null) {
                    const groupTypeIndex = value === UNIQUE_USERS ? undefined : value
                    onChange(groupTypeIndex)
                }
            }}
            data-attr="retention-aggregation-selector"
            dropdownMatchSelectWidth={false}
            options={optionSections}
        />
    )
}
