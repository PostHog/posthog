import React from 'react'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'

const UNIQUE_USERS = -1

interface AggregationSelectProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregationGroupTypeIndex: number | undefined) => void
}

export function AggregationSelect({ aggregationGroupTypeIndex, onChange }: AggregationSelectProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const optionSections: LemonSelectSection<number>[] = [
        {
            title: 'Event Aggregation',
            options: [
                {
                    value: UNIQUE_USERS,
                    label: 'Unique users',
                },
                ...groupTypes.map((groupType) => ({
                    value: groupType.group_type_index,
                    label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
                })),
            ],
        },
    ]

    if (
        [GroupsAccessStatus.HasAccess, GroupsAccessStatus.HasGroupTypes, GroupsAccessStatus.NoAccess].includes(
            groupsAccessStatus
        )
    ) {
        optionSections[0].footer = <GroupIntroductionFooter />
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
            value={aggregationGroupTypeIndex === undefined ? UNIQUE_USERS : aggregationGroupTypeIndex}
            onChange={(value) => {
                if (value) {
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
