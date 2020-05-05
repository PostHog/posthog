import React from 'react'
import { useValues } from 'kea'
import { router } from 'kea-router'
import PropTypes from 'prop-types'

import { addUrlQuestion, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'

export function FilterLink({ property, value, filters, onClick }) {
    const {
        location: { pathname },
    } = useValues(router)
    const search = addUrlQuestion(toParams(filters))
    return (
        <Link
            to={`${pathname}${search}`}
            onClick={event => {
                onClick(property, value)
                event.stopPropagation()
            }}
        >
            {typeof value === 'object' ? JSON.stringify(value) : value && value.replace(/(^\w+:|^)\/\//, '')}
        </Link>
    )
}
FilterLink.propTypes = {
    property: PropTypes.string.isRequired,
    value: PropTypes.string,
    filters: PropTypes.object.isRequired,
    onClick: PropTypes.func.isRequired,
}
