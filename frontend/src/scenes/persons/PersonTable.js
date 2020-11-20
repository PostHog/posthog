import React from 'react'
import PropTypes from 'prop-types'
import { PropertyKeyInfo, keyMapping } from 'lib/components/PropertyKeyInfo'
import { Table, Input } from 'antd'
import { Menu, Dropdown } from 'antd'
import { DownOutlined } from '@ant-design/icons'
export function PersonTable({ properties }) {
    const keyMappingKeys = Object.keys(keyMapping.event)
    const onChange = properties.onChange._handleChange
    const props = { ...properties.props, distinct_id: properties.distinct_id }
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
                return _propertiesTable(item[1], item[0])
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
        else if (properties instanceof Object)
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
        else if (properties === true || properties === false) {
            return (
                <Dropdown
                    overlay={
                        <Menu onClick={onChange}>
                            <Menu.Item key={true} name={_key}>
                                true
                            </Menu.Item>
                            <Menu.Item key={false} name={_key}>
                                false
                            </Menu.Item>
                        </Menu>
                    }
                >
                    <a className="ant-dropdown-link" onClick={(e) => e.preventDefault()}>
                        {properties.toString()} <DownOutlined />
                    </a>
                </Dropdown>
            )
        } else if (typeof properties === 'string' || typeof properties === 'number' || properties === null) {
            return (
                <Input
                    type={typeof properties}
                    disabled={keyMappingKeys.includes(_key)}
                    placeholder={properties ? _key : 'null'}
                    defaultValue={properties}
                    onChange={(e) => onChange(e)}
                    tag={_key}
                    required={true}
                />
            )
        } else return null
    }
}
PersonTable.propTypes = {
    properties: PropTypes.any.isRequired,
}
