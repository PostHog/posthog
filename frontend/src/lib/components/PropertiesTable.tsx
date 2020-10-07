import React, { CSSProperties } from 'react'
import moment from 'moment'
import PropTypes from 'prop-types'
import { PropertyKeyInfo } from './PropertyKeyInfo'
import { Table, Tooltip } from 'antd'
import { EditOutlined, NumberOutlined, CalendarOutlined, BulbOutlined, StopOutlined } from '@ant-design/icons'

type HandledType = 'string' | 'string, parsable as datetime' | 'number' | 'bigint' | 'boolean' | 'undefined' | 'null'
type Type = HandledType | 'symbol' | 'object' | 'function'

const iconStyle: CSSProperties = { marginRight: '0.5rem', opacity: 0.75 }

const typeToIcon: Record<string, JSX.Element> = {
    string: <EditOutlined style={iconStyle} />,
    'string, parsable as datetime': <CalendarOutlined style={iconStyle} />,
    number: <NumberOutlined style={iconStyle} />,
    bigint: <NumberOutlined style={iconStyle} />,
    boolean: <BulbOutlined style={iconStyle} />,
    undefined: <StopOutlined style={iconStyle} />,
    null: <StopOutlined style={iconStyle} />,
}

function PropertyDisplay({ properties }: { properties: any }): JSX.Element {
    let propertiesType: Type = typeof properties
    if (properties === null) propertiesType = 'null'
    else if (propertiesType === 'string' && moment(properties).isValid())
        propertiesType = 'string, parsable as datetime'
    return typeToIcon[propertiesType] ? (
        <>
            <Tooltip title={`Property of type ${propertiesType}.`}>{typeToIcon[propertiesType]}</Tooltip>
            {String(properties)}
        </>
    ) : (
        properties
    )
}

const columns = [
    {
        title: 'key',
        render: function Key(item): JSX.Element {
            return <PropertyKeyInfo value={item[0]} />
        },
    },
    {
        title: 'value',
        render: function Value(item): JSX.Element {
            return <PropertiesTable properties={item[1]} />
        },
    },
]

export function PropertiesTable({ properties }: { properties: any }): JSX.Element {
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
                rowKey={(item) => item[0]}
                size="small"
                pagination={false}
                dataSource={Object.entries(properties)}
            />
        )
    return <PropertyDisplay properties={properties} />
}

PropertiesTable.propTypes = {
    properties: PropTypes.any,
}
