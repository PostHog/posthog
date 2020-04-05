import React from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { Link } from 'react-router-dom'
import { ActionFilterRow } from './ActionFilterRow'

export function ActionFilter(props) {
    const { allFilters } = useValues(entityFilterLogic)
    const { createNewFilter } = useActions(entityFilterLogic)
    return (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => {
                    return <ActionFilterRow filter={filter} index={index} key={index}></ActionFilterRow>
                })}
            <button
                className="btn btn-sm btn-outline-success"
                onClick={() => createNewFilter()}
                style={{ marginTop: '0.5rem' }}
            >
                Add Element
            </button>
        </div>
    )
}
