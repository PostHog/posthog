import React from 'react'
import { Input } from 'antd'
import { FilterType } from '~/types'

export function Formula({
    filters,
    onChange,
}: {
    filters: Partial<FilterType>
    onChange: CallableFunction
}): JSX.Element {
    return (
        <div style={{ maxWidth: 300 }}>
            <Input.Search
                placeholder="(A + B)/(A - B) * 100"
                allowClear
                defaultValue={filters.formula}
                enterButton="Apply"
                onSearch={(value) => onChange(value)}
            />
        </div>
    )
}
