import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'

export function SearchAllBox(): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <div className="mb-05 full-width">
            <Button
                style={{ textAlign: 'left' }}
                data-attr="sessions-filter-open"
                onClick={() => (openFilter ? closeFilterSelect() : openFilterSelect('new'))}
            >
                <span className="text-muted">
                    Filter by user, action, or event properties
                    <SelectDownIcon />
                </span>
            </Button>
        </div>
    )
}
