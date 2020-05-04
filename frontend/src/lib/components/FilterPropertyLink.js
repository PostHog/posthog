import React from 'react'
import { toParams } from '../utils'
import PropTypes from 'prop-types'

import { A } from 'lib/components/A'
import { Property } from 'lib/components/Property'

export function FilterPropertyLink({ property, value, filters, onClick }) {
    const params = toParams({ ...filters, properties: { ...filters.properties, [property]: value } })

    return (
        <A
            href={`${window.location.pathname}${params ? '?' : ''}${params}`}
            onClick={event => {
                if (onClick) {
                    onClick(property, value)
                }
                event.stopPropagation()
            }}
        >
            <Property value={value} />
        </A>
    )
}
FilterPropertyLink.propTypes = {
    property: PropTypes.string.isRequired,
    value: PropTypes.string,
    filters: PropTypes.object.isRequired,
    onClick: PropTypes.func,
}
