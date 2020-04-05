import React from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, EntityTypes } from './actionFilterLogic'
import { Link } from 'react-router-dom'
import { ActionFilterRow } from './ActionFilterRow'

export function ActionFilter(props) {
    const { formattedFilters, newFilters, allFilters } = useValues(entityFilterLogic)
    const { createNewFilter } = useActions(entityFilterLogic)
    return !filtersExist(formattedFilters) ? (
        <div>
            {allFilters &&
                allFilters.map((filter, index) => {
                    return <ActionFilterRow filter={filter} index={index}></ActionFilterRow>
                })}
            <button
                className="btn btn-sm btn-outline-success"
                onClick={() => createNewFilter()}
                style={{ marginTop: '0.5rem' }}
            >
                Add Element
            </button>
        </div>
    ) : (
        <div>
            You don't have any actions defined yet. <Link to="/action">Click here to define an action.</Link>
        </div>
    )
}

const filtersExist = allfilters => {
    if (allfilters == null) {
        return false
    }
    Object.entries(allfilters).forEach((item, index) => {
        let val = item[1]
        if (Array.isArray(val)) {
            return true
        }
    })
    return false
}
