import React from 'react'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Select } from 'antd'
import { groupsModel } from '~/models/groupsModel'

const UNIQUE_USERS = -1

interface AggregationSelectorProps {
    aggregationGroupTypeIndex: number | undefined
    onChange: (aggregationGroupTypeIndex: number | undefined) => void
}

export function RetentionAggregationSelector({
    aggregationGroupTypeIndex,
    onChange,
}: AggregationSelectorProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupTypes } = useValues(groupsModel)

    if (!featureFlags[FEATURE_FLAGS.GROUP_ANALYTICS] || groupTypes.length === 0) {
        return <b>unique users</b>
    }

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
