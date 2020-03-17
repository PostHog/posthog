import React, { Component } from 'react'
import PropTypes from 'prop-types'

export function PropertiesTable({ properties }) {
    if (Array.isArray(properties))
        return (
            <div>
                {properties.map(item => (
                    <span>
                        <PropertiesTable properties={item} />
                        <br />
                    </span>
                ))}
            </div>
        )
    if (properties instanceof Object)
        return (
            <table className="table">
                <tbody>
                    {Object.keys(properties)
                        .sort()
                        .map(key => (
                            <tr>
                                <th>{key}</th>
                                <td>
                                    <PropertiesTable
                                        properties={properties[key]}
                                    />
                                </td>
                            </tr>
                        ))}
                </tbody>
            </table>
        )
    if (properties === true) return 'true'
    if (properties === false) return 'false'
    return properties ? properties : null
}
PropertiesTable.propTypes = {
    properties: PropTypes.any.isRequired,
}
