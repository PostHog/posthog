import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter({ setFilters, filters, typeKey }) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    return (
        <div data-attr="action-filter">
            {localFilters &&
                localFilters.map((filter, index) => (
                    <ActionFilterRow logic={logic} filter={filter} index={index} key={index} />
                ))}
            <Button
                type="primary"
                onClick={() => addFilter()}
                style={{ marginTop: '0.5rem' }}
                data-attr="add-action-event-button"
            >
                Add action/event
            </Button>
        </div>
    )
}
