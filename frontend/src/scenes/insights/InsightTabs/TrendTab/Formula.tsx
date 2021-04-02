import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { FilterType } from '~/types'
import { ShownAsValue } from 'lib/constants'

export function Formula({
    filters,
    onChange,
    onFocus,
}: {
    filters: Partial<FilterType>
    onChange: (formula: string) => void
    onFocus: (hasFocus: boolean, localFormula: string) => void
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
                onChange={(e) => {
                    let value = e.target.value.toLocaleUpperCase()
                    // Only allow typing of allowed characters
                    value = value
                        .split('')
                        .filter((d) => /^[a-zA-Z\ \-\*\^0-9\+\/\(\)]+$/g.test(d))
                        .join('')
                    setValue(value)
                }}
                onFocus={() => onFocus(true, value)}
                onBlur={() => !filters.formula && onFocus(false, value)}
                disabled={filters.shown_as === ShownAsValue.STICKINESS || filters.shown_as === ShownAsValue.LIFECYCLE}
                enterButton="Apply"
                onSearch={onChange}
            />
        </div>
    )
}
