import React from 'react'
import { useValues } from 'kea'
import { Select } from 'antd'
import { groupsModel } from '~/models/groupsModel'

const UNIQUE_USERS = -1

interface AggregationSelectProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregationGroupTypeIndex: number | undefined) => void
    style?: React.CSSProperties
}

export function AggregationSelect({ aggregationGroupTypeIndex, onChange, style }: AggregationSelectProps): JSX.Element {
    const { groupTypes } = useValues(groupsModel)

    return (
        <Select
            value={aggregationGroupTypeIndex === undefined ? UNIQUE_USERS : aggregationGroupTypeIndex}
            onChange={(value) => {
                const groupTypeIndex = value === UNIQUE_USERS ? undefined : value
                onChange(groupTypeIndex)
            }}
            data-attr="retention-aggregation-selector"
            dropdownMatchSelectWidth={false}
            style={style}
        >
            <Select.Option key="unique_users" value={UNIQUE_USERS} data-attr="aggregation-selector-users">
                <div style={{ height: '100%', width: '100%' }}>unique users</div>
            </Select.Option>
            {groupTypes.map((groupType) => (
                <Select.Option
                    key={groupType.group_type_index}
                    value={groupType.group_type_index}
                    data-attr="aggregation-selector-group"
                >
                    <div style={{ height: '100%', width: '100%' }}>unique {groupType.group_type}(s)</div>
                </Select.Option>
            ))}
        </Select>
    )
}
