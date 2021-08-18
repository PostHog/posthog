import React, { CSSProperties, useMemo, useState } from 'react'

import { keyMapping, PropertyKeyInfo } from './PropertyKeyInfo'
import { Dropdown, Input, Menu, Popconfirm, Table } from 'antd'
import { NumberOutlined, BulbOutlined, StopOutlined, DeleteOutlined } from '@ant-design/icons'
import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { IconExternalLink, IconText } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import './PropertiesTable.scss'

type HandledType = 'string' | 'number' | 'bigint' | 'boolean' | 'undefined' | 'null'
type Type = HandledType | 'symbol' | 'object' | 'function'

const keyMappingKeys = Object.keys(keyMapping.event)

const iconStyle: CSSProperties = { display: 'inline-block', marginRight: '0.5rem', opacity: 0.75 }

const typeToIcon: Record<HandledType, JSX.Element> = {
    string: <IconText />,
    number: <NumberOutlined />,
    bigint: <NumberOutlined />,
    boolean: <BulbOutlined />,
    undefined: <StopOutlined />,
    null: <StopOutlined />,
}

interface BasePropertyType {
    rootKey?: string // The key name of the object if it's nested
    onEdit?: (key: string, newValue: any, oldValue?: any) => void // If set, it will allow inline editing
    nestingLevel?: number
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

function ValueDisplay({ value, rootKey, onEdit, nestingLevel }: ValueDisplayType): JSX.Element {
    const [editing, setEditing] = useState(false)
    // Can edit if a key and edit callback is set, the property is custom (i.e. not PostHog), and the value is in the root of the object (i.e. no nested objects)
    const canEdit = rootKey && !keyMappingKeys.includes(rootKey) && (!nestingLevel || nestingLevel <= 1) && onEdit

    const textBasedTypes = ['string', 'number', 'bigint'] // Values that are edited with a text box
    const boolNullTypes = ['boolean', 'null'] // Values that are edited with the boolNullSelect dropdown

    const valueType: Type = value === null ? 'null' : typeof value // typeof null returns 'object' ¯\_(ツ)_/¯

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
        if (rootKey !== undefined && save && onEdit && newValue != value) {
            onEdit(rootKey, newValue, value)
        }
    }

    const valueComponent = (
        <span
            className={canEdit ? 'editable ph-no-capture' : 'ph-no-capture'}
            onClick={() => canEdit && textBasedTypes.includes(valueType) && setEditing(true)}
        >
            {stringWithWBR(String(value))}
        </span>
    )

    return (
        <div className="properties-table-value">
            {typeToIcon[valueType as HandledType] ? (
                <>
                    {!editing ? (
                        <>
                            <div style={iconStyle}>
                                <Tooltip title={`Property of type ${valueType}.`}>
                                    <span>{typeToIcon[valueType as HandledType]}</span>
                                </Tooltip>
                            </div>
                            {canEdit && boolNullTypes.includes(valueType) ? (
                                <Dropdown overlay={boolNullSelect}>{valueComponent}</Dropdown>
                            ) : (
                                <>{valueComponent}</>
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
    sortProperties?: boolean
    onDelete?: (key: string) => void
    className?: string
}

export function PropertiesTable({
    properties,
    rootKey,
    onEdit,
    sortProperties = false,
    nestingLevel = 0,
    onDelete,
    className = '',
}: PropertiesTableType): JSX.Element {
    const objectProperties = useMemo(() => {
        if (!(properties instanceof Object)) {
            return []
        }
        const entries = Object.entries(properties)
        if (!sortProperties) {
            return entries
        }
        return entries.sort((a, b) => {
            if (a[0][0] === '$' && b[0][0] !== '$') {
                return 1
            } else if (a[0][0] !== '$' && b[0][0] === '$') {
                return -1
            }
            return a[0].toLowerCase() < b[0].toLowerCase() ? -1 : 1
        })
    }, [properties, sortProperties])

    const columns = [
        {
            title: 'key',
            render: function Key(item: any): JSX.Element {
                return (
                    <div className="properties-table-key">
                        {onDelete && nestingLevel <= 1 && !keyMappingKeys.includes(item[0]) && (
                            <Popconfirm
                                onConfirm={() => onDelete(item[0])}
                                title={
                                    <>
                                        Are you sure you want to delete this property? <b>This cannot be undone.</b>
                                    </>
                                }
                            >
                                <DeleteOutlined className="cursor-pointer" />
                            </Popconfirm>
                        )}
                        <PropertyKeyInfo value={item[0]} />
                    </div>
                )
            },
        },
        {
            title: 'value',
            render: function Value(item: any): JSX.Element {
                return (
                    <PropertiesTable
                        properties={item[1]}
                        rootKey={item[0]}
                        onEdit={onEdit}
                        nestingLevel={nestingLevel + 1}
                    />
                )
            },
        },
    ]

    if (Array.isArray(properties)) {
        return (
            <div>
                {properties.map((item, index) => (
                    <span key={index}>
                        <PropertiesTable properties={item} nestingLevel={nestingLevel + 1} />
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
                dataSource={objectProperties}
                className={className}
                locale={{ emptyText: 'This property contains an empty object.' }}
            />
        )
    }
    // if none of above, it's a value
    return <ValueDisplay value={properties} rootKey={rootKey} onEdit={onEdit} nestingLevel={nestingLevel} />
}
