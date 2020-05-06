import React from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter({ setFilters, filters, typeKey, setDefaultIfEmpty }) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey, setDefaultIfEmpty })

    const { allFilters } = useValues(logic)
    const { addFilter } = useActions(logic)

    return (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => (
                    <ActionFilterRow logic={logic} filter={filter} index={index} key={index} />
                ))}
            <Button type="primary" onClick={() => addFilter()} style={{ marginTop: '0.5rem' }}>
                Add action/event
            </Button>
        </div>
    )
}
