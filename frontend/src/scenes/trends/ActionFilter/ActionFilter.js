import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter({ setFilters, defaultFilters, showMaths }) {
    const { allFilters, filters } = useValues(entityFilterLogic({ setFilters, defaultFilters }))
    const { createNewFilter, initializeLocalFilters } = useActions(entityFilterLogic({ setFilters, defaultFilters }))

    useEffect(() => {
        if (allFilters.length == 0) {
            let filterscount =
                (filters.actions ? filters.actions.length : 0) + (filters.events ? filters.events.length : 0)
            let allfilters = allFilters.filter(f => f.id != null)
            if (filterscount != allfilters.length) {
                initializeLocalFilters()
            }
        }
    }, [filters])

    return (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => {
                    return <ActionFilterRow filter={filter} index={index} key={index} showMaths={showMaths} />
                })}
            <Button type="primary" onClick={() => createNewFilter()} style={{ marginTop: '0.5rem' }}>
                Add action/event
            </Button>
        </div>
    )
}
