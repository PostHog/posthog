import React from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

export function SearchAllBox(): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <div className="mb-05">
            <Button
                data-attr="sessions-filter-open"
                onClick={() => (openFilter ? closeFilterSelect() : openFilterSelect('new'))}
            >
                <SearchOutlined />
                <span className="text-muted">Search for users, events, actions...</span>
            </Button>
        </div>
    )
}
