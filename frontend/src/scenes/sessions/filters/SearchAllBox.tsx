import React from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

export function SearchAllBox(): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <div className="mb-05 full-width">
            <Button
                className="full-width"
                style={{ textAlign: 'left' }}
                data-attr="sessions-filter-open"
                onClick={() => (openFilter ? closeFilterSelect() : openFilterSelect('new'))}
            >
                <SearchOutlined />
                <span className="text-muted">Filter sessions by users, actions, events, ...</span>
            </Button>
        </div>
    )
}
