import React from 'react'
import { useValues, useActions } from 'kea'
import { Checkbox } from 'antd'
import { compareFilterLogic } from './compareFilterLogic'
import { LIFECYCLE } from 'lib/constants'

export function CompareFilter(props) {
    const { compare } = useValues(compareFilterLogic)
    const { setCompare } = useActions(compareFilterLogic)
    const {
        filters: { shown_as },
    } = props
    return (
        <Checkbox
            onChange={(e) => {
                setCompare(e.target.checked)
            }}
            checked={compare}
            style={{ marginLeft: 8, marginRight: 6 }}
            disabled={shown_as === LIFECYCLE}
        >
            Compare Previous
        </Checkbox>
    )
}
