import React from 'react'
import { useValues, useActions } from 'kea'
import { Checkbox } from 'antd'
import { compareFilterLogic } from './compareFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function CompareFilter(): JSX.Element {
    const { insight } = useValues(insightLogic)
    const { compare, disabled } = useValues(compareFilterLogic({ id: insight?.id || 'new' }))
    const { setCompare } = useActions(compareFilterLogic({ id: insight?.id || 'new' }))
    return (
        <Checkbox
            onChange={(e) => {
                setCompare(e.target.checked)
            }}
            checked={compare}
            style={{ marginLeft: 8, marginRight: 6 }}
            disabled={disabled}
        >
            Compare<span className="hide-lte-md"> previous</span>
        </Checkbox>
    )
}
