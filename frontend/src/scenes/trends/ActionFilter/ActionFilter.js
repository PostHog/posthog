import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter({ setFilters, filters, defaultFilters, typeKey, setDefaultIfEmpty }) {
    const logic = entityFilterLogic({ setFilters, filters, defaultFilters, typeKey, setDefaultIfEmpty })

    const { allFilters } = useValues(logic)
    const { createNewFilter } = useActions(logic)

    return (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => {
                    return <ActionFilterRow logic={logic} filter={filter} index={index} key={index} typeKey={typeKey} />
                })}
            <Button type="primary" onClick={() => createNewFilter()} style={{ marginTop: '0.5rem' }}>
                Add action/event
            </Button>
        </div>
    )
}
