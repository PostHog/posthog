import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { FilterType } from '~/types'
import { LIFECYCLE, STICKINESS } from 'lib/constants'

export function Formula({
    filters,
    onChange,
}: {
    filters: Partial<FilterType>
    onChange: (formula: string) => void
}): JSX.Element {
    const [value, setValue] = useState(filters.formula)
    useEffect(() => {
        setValue(filters.formula)
    }, [filters.formula])
    return (
        <div style={{ maxWidth: 300 }}>
            <Input.Search
                placeholder="e.g. (A + B)/(A - B) * 100"
                allowClear
                value={value}
                onChange={(e) => setValue(e.target.value.toLocaleUpperCase())}
                disabled={filters.shown_as === STICKINESS || filters.shown_as === LIFECYCLE}
                enterButton="Apply"
                onSearch={onChange}
            />
        </div>
    )
}
