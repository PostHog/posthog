import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter(props) {
    const { allFilters, filters } = useValues(entityFilterLogic)
    const { createNewFilter, initializeLocalFilters } = useActions(entityFilterLogic)

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
                    return <ActionFilterRow filter={filter} index={index} key={index}></ActionFilterRow>
                })}
            <Button type="primary" onClick={() => createNewFilter()} style={{ marginTop: '0.5rem' }}>
                Add Element
            </Button>
        </div>
    )
}
