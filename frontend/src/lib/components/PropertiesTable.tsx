import React, { CSSProperties, useState } from 'react'
import moment from 'moment'
import PropTypes from 'prop-types'
import { keyMapping, PropertyKeyInfo } from './PropertyKeyInfo'
import { Dropdown, Input, Menu, Table, Tooltip } from 'antd'
import { NumberOutlined, CalendarOutlined, BulbOutlined, StopOutlined } from '@ant-design/icons'
import { isURL } from 'lib/utils'
import { IconExternalLink, IconText } from 'lib/components/icons'
import './PropertiesTable.scss'

type HandledType = 'string' | 'string, parsable as datetime' | 'number' | 'bigint' | 'boolean' | 'undefined' | 'null'
type Type = HandledType | 'symbol' | 'object' | 'function'

const iconStyle: CSSProperties = { marginRight: '0.5rem', opacity: 0.75 }

const typeToIcon: Record<string, JSX.Element> = {
    string: <IconText style={iconStyle} />,
    'string, parsable as datetime': <CalendarOutlined style={iconStyle} />,
    number: <NumberOutlined style={iconStyle} />,
    bigint: <NumberOutlined style={iconStyle} />,
    boolean: <BulbOutlined style={iconStyle} />,
    undefined: <StopOutlined style={iconStyle} />,
    null: <StopOutlined style={iconStyle} />,
}

interface BasePropertyType {
    rootKey?: string // The key name of the object if it's nested
    onEdit?: (key: string | undefined, newValue: any, oldValue?: any) => void // If set, it will allow inline editing
}

interface ValueDisplayType extends BasePropertyType {
    value: any
}

function EditTextValueComponent({
    value,
    onChange,
}: {
    value: any
    onChange: (newValue: any, save: boolean) => void
}): JSX.Element {
    return (
        <Input
            defaultValue={value}
            autoFocus
            onBlur={() => onChange(null, false)}
            onPressEnter={(e) => onChange((e.target as HTMLInputElement).value, true)}
        />
    )
}

function ValueDisplay({ value, rootKey, onEdit }: ValueDisplayType): JSX.Element {
    const [editing, setEditing] = useState(false)
    const keyMappingKeys = Object.keys(keyMapping.event)
    const canEdit = rootKey && !keyMappingKeys.includes(rootKey) && onEdit

    const textBasedTypes = ['string', 'number', 'bigint'] // Values that are edited with a text box
    const boolNullTypes = ['boolean', 'null'] // Values that are edited with the boolNullSelect dropdown

    let valueType: Type = typeof value
    if (value === null) {
        valueType = 'null'
    } else if (valueType === 'string' && moment(value).isValid()) {
        valueType = 'string, parsable as datetime'
    }

    const boolNullSelect = (
        <Menu
            onClick={({ key }) => {
                let val = null
                if (key === 't') {
                    val = true
                } else if (key === 'f') {
                    val = false
                }
                handleValueChange(val, true)
            }}
        >
            <Menu.Item key="t">true</Menu.Item>
            <Menu.Item key="f">false</Menu.Item>
            <Menu.Item key="n" danger>
                null
            </Menu.Item>
        </Menu>
    )

    const handleValueChange = (newValue: any, save: boolean): void => {
        setEditing(false)
        if (save && onEdit && newValue != value) {
            onEdit(rootKey, newValue, value)
        }
    }

    const valueComponent = (
        <span
            className={canEdit ? `editable` : ''}
            onClick={() => canEdit && textBasedTypes.includes(valueType) && setEditing(true)}
        >
            {String(value)}
        </span>
    )

    return (
        <div className="properties-table-value">
            {typeToIcon[valueType] ? (
                <>
                    {!editing ? (
                        <>
                            <Tooltip title={`Property of type ${valueType}.`}>{typeToIcon[valueType]}</Tooltip>
                            {canEdit && boolNullTypes.includes(valueType) ? (
                                <Dropdown overlay={boolNullSelect}>{valueComponent}</Dropdown>
                            ) : (
                                <> {valueComponent}</>
                            )}

                            {isURL(value) && (
                                <a href={value} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 4 }}>
                                    <IconExternalLink />
                                </a>
                            )}
                        </>
                    ) : (
                        <EditTextValueComponent value={value} onChange={handleValueChange} />
                    )}
                </>
            ) : (
                value
            )}
        </div>
    )
}

interface PropertiesTableType extends BasePropertyType {
    properties: any
}

export function PropertiesTable({ properties, rootKey, onEdit }: PropertiesTableType): JSX.Element {
    const columns = [
        {
            title: 'key',
            render: function Key(item: any): JSX.Element {
                return <PropertyKeyInfo value={item[0]} />
            },
        },
        {
            title: 'value',
            render: function Value(item: any): JSX.Element {
                return <PropertiesTable properties={item[1]} rootKey={item[0]} onEdit={onEdit} />
            },
        },
    ]

    if (Array.isArray(properties)) {
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
    }
    if (properties instanceof Object) {
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
    }
    // if none of above, it's a value
    return <ValueDisplay value={properties} rootKey={rootKey} onEdit={onEdit} />
}

PropertiesTable.propTypes = {
    properties: PropTypes.any,
}
