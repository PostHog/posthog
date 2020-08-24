import React from 'react'
import PropTypes, { bool } from 'prop-types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Table,Input } from 'antd'


export function PersonTable({ properties}) {
    const onChange = properties.onChange._handleChange
    const props = {...properties.props, distinct_id:properties.distinct_id}

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
                return _propertiesTable(item[1],item[0])
            },
        },
    ]
    return _propertiesTable(props)

    function _propertiesTable(properties, _key = null) {
        if (Array.isArray(properties))
            return (
                <div>
                    {properties.map((item, index) => (
                        <span key={index}>
                            {_propertiesTable(item, _key)}
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
                    rowKey={(item) => item[0]}
                    size="small"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    dataSource={Object.entries(properties)}
                />
            )
        if (properties === true) return 'true'
        if (properties === false) return 'false'
        if (typeof(properties) === 'string'){
            return (<Input 
                disabled = {_key === 'distinct_id'} 
                placeholder = {_key} 
                defaultValue = {properties} 
                onChange = {onChange} tag = {_key} 
                required = {true}
            />)
        }else return null
    }
}
PersonTable.propTypes = {
    properties: PropTypes.any.isRequired,
}
