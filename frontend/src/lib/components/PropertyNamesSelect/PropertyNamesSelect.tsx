import { Select } from 'antd'
import { usePersonProperies } from 'lib/api/person-properties'
import React from 'react'

export const PropertyNamesSelect = ({
    onChange,
}: {
    onChange: (selectedProperties: string[]) => void
}): JSX.Element => {
    /*
        Provides a super simple multiselect box for selecting property names.

        NOTE: this handles it's own state rather than a logic to avoid
        complexity
    */

    const properties = usePersonProperies()

    return (
        <Select
            mode="multiple"
            placeholder="Select property names"
            style={{ width: '100%', minWidth: '200px' }}
            onChange={onChange}
        >
            <Select.Option value="$all">All</Select.Option>
            {properties?.map((property) => (
                <Select.Option key={property.name} value={property.name}>
                    {property.name}
                </Select.Option>
            ))}
        </Select>
    )
}
