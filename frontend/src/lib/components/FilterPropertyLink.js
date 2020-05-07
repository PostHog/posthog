import React from 'react'
import { combineUrl } from 'kea-router'
import PropTypes from 'prop-types'

import { Property } from 'lib/components/Property'
import { Link } from 'lib/components/Link'

export function FilterPropertyLink({ property, value, filters, onClick }) {
    const { url } = combineUrl(window.location.pathname, {
        ...filters,
        properties: { ...filters.properties, [property]: value },
    })

    return (
        <Link
            to={url}
            onClick={event => {
                if (onClick) {
                    onClick(property, value)
                }
            }}
        >
            <Property value={value} />
        </Link>
    )
}
FilterPropertyLink.propTypes = {
    property: PropTypes.string.isRequired,
    value: PropTypes.string,
    filters: PropTypes.object.isRequired,
    onClick: PropTypes.func,
}
