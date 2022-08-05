import React, { useMemo, useState } from 'react'

import { keyMappingKeys, PropertyKeyInfo } from './PropertyKeyInfo'
import { Dropdown, Input, Menu, Popconfirm } from 'antd'
import { isURL } from 'lib/utils'
import { IconDeleteForever, IconOpenInNew } from 'lib/components/icons'
import './PropertiesTable.scss'
import { LemonTable, LemonTableColumns } from './LemonTable'
import { CopyToClipboardInline } from './CopyToClipboard'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { LemonButton } from './LemonButton'
import { NewPropertyComponent } from 'scenes/persons/NewPropertyComponent'

type HandledType = 'string' | 'number' | 'bigint' | 'boolean' | 'undefined' | 'null'
type Type = HandledType | 'symbol' | 'object' | 'function'

interface BasePropertyType {
    rootKey?: string // The key name of the object if it's nested
    onEdit?: (key: string, newValue: any, oldValue?: any) => void // If set, it will allow inline editing
    nestingLevel?: number
}

interface ValueDisplayType extends BasePropertyType {
    value: any
    useDetectedPropertyType?: boolean
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

function ValueDisplay({
    value,
    rootKey,
    onEdit,
    nestingLevel,
    useDetectedPropertyType,
}: ValueDisplayType): JSX.Element {
    const { describeProperty } = useValues(propertyDefinitionsModel)

    const [editing, setEditing] = useState(false)
    // Can edit if a key and edit callback is set, the property is custom (i.e. not PostHog), and the value is in the root of the object (i.e. no nested objects)
    const canEdit = rootKey && !keyMappingKeys.includes(rootKey) && (!nestingLevel || nestingLevel <= 1) && onEdit

    const textBasedTypes = ['string', 'number', 'bigint'] // Values that are edited with a text box
    const boolNullTypes = ['boolean', 'null'] // Values that are edited with the boolNullSelect dropdown

    let propertyType
    if (rootKey && useDetectedPropertyType) {
        propertyType = describeProperty(rootKey)
    }
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
                    <div className="property-value-type">{propertyType || valueType}</div>
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
    searchable?: boolean
    /** Whether this table should be style for being embedded. Default: true. */
    embedded?: boolean
    onDelete?: (key: string) => void
    className?: string
    /* only event types are detected and so describe-able. see https://github.com/PostHog/posthog/issues/9245 */
    useDetectedPropertyType?: boolean
}

export function PropertiesTable({
    properties,
    rootKey,
    onEdit,
    sortProperties = false,
    searchable = false,
    embedded = true,
    nestingLevel = 0,
    onDelete,
    className,
    useDetectedPropertyType,
}: PropertiesTableType): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')

    if (Array.isArray(properties)) {
        return (
            <div>
                {properties.length ? (
                    properties.map((item, index) => (
                        <PropertiesTable
                            key={index}
                            properties={item}
                            nestingLevel={nestingLevel + 1}
                            useDetectedPropertyType={
                                ['$set', '$set_once'].some((s) => s === rootKey) ? false : useDetectedPropertyType
                            }
                        />
                    ))
                ) : (
                    <div className="property-value-type">ARRAY (EMPTY)</div>
                )}
            </div>
        )
    }

    if (properties instanceof Object) {
        const columns: LemonTableColumns<Record<string, any>> = [
            {
                key: 'key',
                title: 'Key',
                render: function Key(_, item: any): JSX.Element {
                    return (
                        <div className="properties-table-key">
                            <PropertyKeyInfo value={item[0]} />
                        </div>
                    )
                },
                sorter: (a, b) => String(a[0]).localeCompare(String(b[0])),
            },
            {
                key: 'value',
                title: 'Value',
                render: function Value(_, item: any): JSX.Element {
                    return (
                        <PropertiesTable
                            properties={item[1]}
                            rootKey={item[0]}
                            onEdit={onEdit}
                            nestingLevel={nestingLevel + 1}
                            useDetectedPropertyType={
                                ['$set', '$set_once'].some((s) => s === rootKey) ? false : useDetectedPropertyType
                            }
                        />
                    )
                },
            },
        ]

        if (onDelete && nestingLevel === 0) {
            columns.push({
                key: 'delete',
                title: '',
                width: 0,
                render: function Delete(_, item: any): JSX.Element | false {
                    return (
                        !keyMappingKeys.includes(item[0]) &&
                        !String(item[0]).startsWith('$initial_') && (
                            <Popconfirm
                                onConfirm={() => onDelete(item[0])}
                                okButtonProps={{ danger: true }}
                                okText="Delete"
                                title={
                                    <>
                                        Are you sure you want to delete property <code>{item[0]}</code>?{' '}
                                        <b>This cannot be undone.</b>
                                    </>
                                }
                                placement="left"
                            >
                                <LemonButton icon={<IconDeleteForever />} status="danger" size="small" />
                            </Popconfirm>
                        )
                    )
                },
            })
        }

        const objectProperties = useMemo(() => {
            if (!(properties instanceof Object)) {
                return []
            }
            let entries = Object.entries(properties)
            if (searchTerm) {
                const normalizedSearchTerm = searchTerm.toLowerCase()
                entries = entries.filter(
                    ([key, value]) =>
                        key.toLowerCase().includes(normalizedSearchTerm) ||
                        JSON.stringify(value).toLowerCase().includes(normalizedSearchTerm)
                )
            }
            if (sortProperties) {
                entries.sort(([aKey], [bKey]) => {
                    if (aKey[0] === '$' && bKey[0] !== '$') {
                        return 1
                    } else if (aKey[0] !== '$' && bKey[0] === '$') {
                        return -1
                    }
                    return aKey.toLowerCase() < bKey.toLowerCase() ? -1 : 1
                })
            }
            return entries
        }, [properties, sortProperties, searchTerm])

        return Object.keys(properties).length > 0 ? (
            <>
                {searchable && (
                    <div className="flex justify-between gap-4">
                        <Input.Search
                            placeholder="Search for property keys and values"
                            className="mb-4"
                            allowClear
                            enterButton
                            style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                            value={searchTerm}
                            onChange={(e) => {
                                setSearchTerm(e.target.value)
                            }}
                        />
                        {onEdit && <NewPropertyComponent editProperty={onEdit} />}
                    </div>
                )}
                <LemonTable
                    columns={columns}
                    showHeader={!embedded}
                    size="small"
                    rowKey="0"
                    embedded={embedded}
                    dataSource={objectProperties}
                    className={className}
                />
            </>
        ) : (
            <div className="property-value-type">OBJECT (EMPTY)</div>
        )
    }
    // if none of above, it's a value
    return (
        <ValueDisplay
            value={properties}
            rootKey={rootKey}
            onEdit={onEdit}
            nestingLevel={nestingLevel}
            useDetectedPropertyType={useDetectedPropertyType}
        />
    )
}
