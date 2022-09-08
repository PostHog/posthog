import React from 'react'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

const UNIQUE_USERS = -1

interface AggregationSelectProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregationGroupTypeIndex: number | undefined) => void
}

export function AggregationSelect({ aggregationGroupTypeIndex, onChange }: AggregationSelectProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const options: LemonSelectOption<number>[] = [
        {
            value: UNIQUE_USERS,
            label: 'Unique users',
        },
    ]

    groupTypes.forEach((groupType) => {
        options.push({
            value: groupType.group_type_index,
            label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
        })
    })

    if (
        [GroupsAccessStatus.HasAccess, GroupsAccessStatus.HasGroupTypes, GroupsAccessStatus.NoAccess].includes(
            groupsAccessStatus
        )
    ) {
        options.push({
            value: -2,
            disabled: true,
            label: (
                <div>
                    Unique Groups –{' '}
                    <Link
                        to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                        target="_blank"
                        data-attr="group-analytics-learn-more"
                    >
                        Learn more
                    </Link>
                </div>
            ),
        })
    }

    return (
        <LemonSelect
            value={aggregationGroupTypeIndex === undefined ? UNIQUE_USERS : aggregationGroupTypeIndex}
            onChange={(value) => {
                if (value) {
                    const groupTypeIndex = value === UNIQUE_USERS ? undefined : value
                    onChange(groupTypeIndex)
                }
            }}
            data-attr="retention-aggregation-selector"
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
