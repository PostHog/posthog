import React, { useState, useEffect } from 'react'
import { Input } from 'antd'
import { FilterType } from '~/types'

export function Formula({
    filters,
    onChange,
    onFocus,
    autoFocus,
    allowClear = true,
}: {
    filters: Partial<FilterType>
    onChange: (formula: string) => void
    onFocus?: (hasFocus: boolean, localFormula: string) => void
    autoFocus?: boolean
    allowClear?: boolean
}): JSX.Element {
    const [value, setValue] = useState(filters.formula)
    useEffect(() => {
        setValue(filters.formula)
    }, [filters.formula])
    return (
        <div style={{ maxWidth: 300 }}>
            <Input.Search
                placeholder="e.g. (A + B)/(A - B) * 100"
                allowClear={allowClear}
                autoFocus={autoFocus}
                value={value}
                onChange={(e) => {
                    let changedValue = e.target.value.toLocaleUpperCase()
                    // Only allow typing of allowed characters
                    changedValue = changedValue
                        .split('')
                        .filter((d) => /^[a-zA-Z\ \-\*\^0-9\+\/\(\)]+$/g.test(d))
                        .join('')
                    setValue(changedValue)
                }}
                onFocus={() => onFocus && onFocus(true, value)}
                onBlur={() => !filters.formula && onFocus && onFocus(false, value)}
                enterButton="Apply"
                onSearch={onChange}
            />
        </div>
    )
}
