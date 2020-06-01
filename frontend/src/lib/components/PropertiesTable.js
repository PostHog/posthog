import React from 'react'
import PropTypes from 'prop-types'
import { PropertyKeyInfo } from './PropertyKeyInfo'
import { Table } from 'antd'

const columns = [
    {
        title: 'key',
        render: function renderKey(item) {
            return <PropertyKeyInfo value={item[0]} />
        },
    },
    {
        title: 'value',
        render: function renderValue(item) {
            return <PropertiesTable properties={item[1]} />
        },
    },
]

export function PropertiesTable({ properties }) {
    if (Array.isArray(properties))
        return (
            <div>
                {properties.map((item, index) => (
                    <span key={index}>
                        <PropertiesTable properties={item} />
                        <br />
                    </span>
                ))}
            </div>
        )
    if (properties instanceof Object)
        return (
            <Table
                columns={columns}
                showHeader={false}
                rowKey={item => item[0]}
                size="small"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                dataSource={Object.entries(properties)}
            />
        )
    if (properties === true) return 'true'
    if (properties === false) return 'false'
    return properties ? properties : null
}
PropertiesTable.propTypes = {
    properties: PropTypes.any.isRequired,
}
