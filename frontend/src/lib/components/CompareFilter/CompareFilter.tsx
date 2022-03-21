import React from 'react'
import { useValues, useActions } from 'kea'
import { Checkbox } from 'antd'
import { compareFilterLogic } from './compareFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function CompareFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { compare, disabled } = useValues(compareFilterLogic(insightProps))
    const { setCompare } = useActions(compareFilterLogic(insightProps))

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
