import React, { CSSProperties, useState } from 'react'
import moment from 'moment'
import PropTypes from 'prop-types'
import { keyMapping, PropertyKeyInfo } from './PropertyKeyInfo'
import { Input, Table, Tooltip } from 'antd'
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

function EditValueComponent({
    value,
    valueType,
    onChange,
}: {
    value: any
    valueType: string
    onChange: (newValue: any, save: boolean) => void
}): JSX.Element {
    return (
        <>
            {(valueType === 'string' || valueType === 'number') && (
                <Input
                    defaultValue={value}
                    autoFocus
                    onBlur={() => onChange(null, false)}
                    onPressEnter={(e) => onChange((e.target as HTMLInputElement).value, true)}
                />
            )}
        </>
    )
}

function ValueDisplay({ value, rootKey, onEdit }: ValueDisplayType): JSX.Element {
    const [editing, setEditing] = useState(false)
    const keyMappingKeys = Object.keys(keyMapping.event)
    const canEdit = rootKey && !keyMappingKeys.includes(rootKey) && onEdit

    let valueType: Type = typeof value
    if (value === null) {
        valueType = 'null'
    } else if (valueType === 'string' && moment(value).isValid()) {
        valueType = 'string, parsable as datetime'
    }

    const handleValueChange = (newValue: any, save: boolean): void => {
        setEditing(false)
        if (save && onEdit && newValue != value) {
            onEdit(rootKey, newValue, value)
        }
    }

    return (
        <div className="properties-table-value">
            {typeToIcon[valueType] ? (
                <>
                    {!editing ? (
                        <>
                            <Tooltip title={`Property of type ${valueType}.`}>{typeToIcon[valueType]}</Tooltip>
                            <span className={canEdit ? `editable` : ''} onClick={() => canEdit && setEditing(true)}>
                                {String(value)}
                            </span>
                            {isURL(value) && (
                                <a href={value} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 4 }}>
                                    <IconExternalLink />
                                </a>
                            )}
                        </>
                    ) : (
                        <EditValueComponent value={value} valueType={valueType} onChange={handleValueChange} />
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
