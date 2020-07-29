import React from 'react'
import { useValues, useActions } from 'kea'
import { Checkbox } from 'antd'
import { compareFilterLogic } from './compareFilterLogic'

export function CompareFilter() {
    const { compare } = useValues(compareFilterLogic)
    const { setCompare } = useActions(compareFilterLogic)
    return (
        <Checkbox
            onChange={(e) => {
                setCompare(e.target.checked)
            }}
            checked={compare}
            style={{ marginLeft: 8, marginRight: 6 }}
        >
            Compare Previous
        </Checkbox>
    )
}
