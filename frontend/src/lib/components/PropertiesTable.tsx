import React, { useMemo, useState } from 'react'

import { keyMappingKeys, PropertyKeyInfo } from './PropertyKeyInfo'
import { Dropdown, Input, Menu, Popconfirm } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { isURL } from 'lib/utils'
import { IconOpenInNew } from 'lib/components/icons'
import './PropertiesTable.scss'
import { LemonTable, LemonTableColumns } from './LemonTable'
import { CopyToClipboardInline } from './CopyToClipboard'

type HandledType = 'string' | 'number' | 'bigint' | 'boolean' | 'undefined' | 'null'
type Type = HandledType | 'symbol' | 'object' | 'function'

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
    const valueString: string = value === null ? 'null' : String(value) // typeof null returns 'object' ¯\_(ツ)_/¯

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
            {!isURL(value) ? (
                valueString
            ) : (
                <a href={value} target="_blank" rel="noopener noreferrer" className="value-link">
                    <span>{valueString}</span>
                    <IconOpenInNew />
                </a>
            )}
        </span>
    )

    return (
        <div className="properties-table-value">
            {!editing ? (
                <>
                    {canEdit && boolNullTypes.includes(valueType) ? (
                        <Dropdown
                            overlay={
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
                            }
                        >
                            {valueComponent}
                        </Dropdown>
                    ) : (
                        <CopyToClipboardInline
                            description="property value"
                            explicitValue={valueString}
                            selectable
                            isValueSensitive
                        >
                            {valueComponent}
                        </CopyToClipboardInline>
                    )}
                    <div className="property-value-type">{valueType}</div>
                </>
            ) : (
                <EditTextValueComponent value={value} onChange={handleValueChange} />
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
    className,
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

    if (Array.isArray(properties)) {
        return (
            <div>
                {properties.length ? (
                    properties.map((item, index) => (
                        <PropertiesTable key={index} properties={item} nestingLevel={nestingLevel + 1} />
                    ))
                ) : (
                    <div className="property-value-type">ARRAY (EMPTY)</div>
                )}
            </div>
        )
    }

    const columns: LemonTableColumns<Record<string, any>> = [
        {
            title: 'key',
            width: '15rem',
            render: function Key(_, item: any): JSX.Element {
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
            render: function Value(_, item: any): JSX.Element {
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

    if (properties instanceof Object) {
        return (
            <LemonTable
                columns={columns}
                showHeader={false}
                size="small"
                rowKey="0"
                embedded
                dataSource={objectProperties}
                className={className}
                emptyState="This property contains an empty object."
            />
        )
    }
    // if none of above, it's a value
    return <ValueDisplay value={properties} rootKey={rootKey} onEdit={onEdit} nestingLevel={nestingLevel} />
}
