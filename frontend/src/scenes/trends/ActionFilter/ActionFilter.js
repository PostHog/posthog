import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

export function ActionFilter({ setFilters, defaultFilters, showMaths, typeKey }) {
    const { allFilters } = useValues(entityFilterLogic({ setFilters, defaultFilters, typeKey }))
    const { createNewFilter } = useActions(entityFilterLogic({ setFilters, defaultFilters, typeKey }))

    return (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => {
                    return (
                        <ActionFilterRow
                            filter={filter}
                            index={index}
                            key={index}
                            showMaths={showMaths}
                            typeKey={typeKey}
                        />
                    )
                })}
            <Button type="primary" onClick={() => createNewFilter()} style={{ marginTop: '0.5rem' }}>
                Add action/event
            </Button>
        </div>
    )
}
