import React from 'react'
import { useValues } from 'kea'
import { Select } from 'antd'
import { groupsModel } from '~/models/groupsModel'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'

const UNIQUE_USERS = -1

interface AggregationSelectProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregationGroupTypeIndex: number | undefined) => void
}

export function AggregationSelect({ aggregationGroupTypeIndex, onChange }: AggregationSelectProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)

    return (
        <Select
            value={aggregationGroupTypeIndex === undefined ? UNIQUE_USERS : aggregationGroupTypeIndex}
            onChange={(value) => {
                const groupTypeIndex = value === UNIQUE_USERS ? undefined : value
                onChange(groupTypeIndex)
            }}
            data-attr="retention-aggregation-selector"
            dropdownMatchSelectWidth={false}
        >
            <Select.Option key="unique_users" value={UNIQUE_USERS} data-attr="aggregation-selector-users">
                <div style={{ height: '100%', width: '100%' }}>Unique users</div>
            </Select.Option>
            {groupTypes.map((groupType) => (
                <Select.Option
                    key={groupType.group_type_index}
                    value={groupType.group_type_index}
                    data-attr="aggregation-selector-group"
                >
                    <div style={{ height: '100%', width: '100%' }}>
                        Unique {aggregationLabel(groupType.group_type_index).plural}
                    </div>
                </Select.Option>
            ))}
            {/* :KLUDGE: Select only allows Select.Option as children, so render groups option directly rather than as a child */}
            {GroupsIntroductionOption({ value: -2 })}
        </Select>
    )
}
