import React from 'react'
import { combineUrl } from 'kea-router'
import PropTypes from 'prop-types'

import { Property } from 'lib/components/Property'
import { Link } from 'lib/components/Link'
import { parseProperties } from 'lib/components/PropertyFilters/propertyFilterLogic'

export function FilterPropertyLink({ property, value, filters, onClick }) {
    const cleanedProperties = Array.isArray(filters.properties)
        ? filters.properties
        : parseProperties(filters.properties)

    const properties = cleanedProperties.find(p => p.key === property && p.value === value && !p.operator)
        ? cleanedProperties.filter(p => p.key !== property || p.value !== value || p.operator)
        : [...cleanedProperties, { key: property, value: value }]

    const { url } = combineUrl(window.location.pathname, {
        ...filters,
        properties,
    })

    return (
        <Link
            to={url}
            onClick={() => {
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
