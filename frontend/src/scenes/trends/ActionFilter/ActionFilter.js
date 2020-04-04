import React from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, EntityTypes } from './actionFilterLogic'
import { Link } from 'react-router-dom'
import { ActionFilterRow } from './ActionFilterRow'
import { capitalizeFirstLetter } from '~/lib/utils'

export function ActionFilter(props) {
    const { formattedFilters, selectedFilter, newFilters } = useValues(entityFilterLogic)
    const { createNewFilter } = useActions(entityFilterLogic)
    return !filtersExist(formattedFilters) ? (
        <div>
            {Object.entries(formattedFilters).map((item, index) => {
                let key = item[0]
                let filters = item[1]
                if (Array.isArray(filters)) {
                    return (
                        <div>
                            {filters && filters.length > 0 && (
                                <p className="mt-3 mb-0 font-weight-bold">{capitalizeFirstLetter(key)}</p>
                            )}
                            {filters.map((filter, index) => {
                                return <ActionFilterRow filter={filter} type={key} index={index}></ActionFilterRow>
                            })}
                        </div>
                    )
                }
            })}
            {newFilters && newFilters.length > 0 && <p className="mt-3 mb-0 font-weight-bold">{'Unspecified'}</p>}
            {newFilters &&
                newFilters.map((_, index) => {
                    let filter = {}
                    return <ActionFilterRow filter={filter} type={EntityTypes.NEW} index={index}></ActionFilterRow>
                })}
            <button
                className="btn btn-sm btn-outline-success"
                onClick={() => createNewFilter()}
                style={{ marginTop: '0.5rem' }}
            >
                Add action
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
