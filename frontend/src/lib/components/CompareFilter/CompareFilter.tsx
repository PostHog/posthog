import React from 'react'
import { useValues, useActions } from 'kea'
import { Checkbox } from 'antd'
import { compareFilterLogic } from './compareFilterLogic'

export function CompareFilter(): JSX.Element | null {
    const { compare, disabled } = useValues(compareFilterLogic)
    const { setCompare } = useActions(compareFilterLogic)

    // Hide compare filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    return (
        <Checkbox
            onChange={(e) => {
                setCompare(e.target.checked)
            }}
            checked={compare}
            style={{ marginLeft: 8, marginRight: 6 }}
            disabled={disabled}
        >
            Compare<span className="hide-lte-md"> to previous</span>
        </Checkbox>
    )
}
