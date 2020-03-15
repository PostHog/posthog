import React from 'react'
import { toParams } from '../utils'
import { createBrowserHistory } from 'history'
import PropTypes from 'prop-types'

import { Link } from 'react-router-dom'

export function FilterLink({ property, value, filters, onClick }) {
    let history = createBrowserHistory()
    return (
        <Link
            to={{
                pathname: history.pathname,
                search: toParams(filters),
            }}
            onClick={event => {
                onClick(property, value)
                event.stopPropagation()
            }}
        >
            {typeof value === 'object'
                ? JSON.stringify(value)
                : value && value.replace(/(^\w+:|^)\/\//, '')}
        </Link>
    )
}
FilterLink.propTypes = {
    property: PropTypes.string.isRequired,
    value: PropTypes.string.isRequired,
    filters: PropTypes.object.isRequired,
    onClick: PropTypes.func.isRequired,
}
