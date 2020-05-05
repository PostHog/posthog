import React from 'react'
import { toParams } from '../utils'
import PropTypes from 'prop-types'

import { Property } from 'lib/components/Property'
import { Link } from 'lib/components/Link'

export function FilterPropertyLink({ property, value, filters, onClick }) {
    const params = toParams({ ...filters, properties: { ...filters.properties, [property]: value } })

    return (
        <Link
            to={`${window.location.pathname}${params ? '?' : ''}${params}`}
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
