import React, { CSSProperties } from 'react'
import moment from 'moment'
import PropTypes from 'prop-types'
import { PropertyKeyInfo } from './PropertyKeyInfo'
import { Table, Tooltip } from 'antd'
import { EditOutlined, NumberOutlined, CalendarOutlined, BulbOutlined, StopOutlined } from '@ant-design/icons'
import { isURL } from 'lib/utils'

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

function ValueDisplay({ value }: { value: any }): JSX.Element {
    let valueType: Type = typeof value
    if (value === null) valueType = 'null'
    else if (valueType === 'string' && moment(value).isValid()) valueType = 'string, parsable as datetime'
    return typeToIcon[valueType] ? (
        <>
            <Tooltip title={`Property of type ${valueType}.`}>{typeToIcon[valueType]}</Tooltip>
            {isURL(value) ? (
                <a href={value} target="_blank" rel="noopener noreferrer">
                    {String(value)}
                </a>
            ) : (
                String(value)
            )}
        </>
    ) : (
        value
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
    // if none of above, it's a value
    return <ValueDisplay value={properties} />
}

PropertiesTable.propTypes = {
    properties: PropTypes.any,
}
