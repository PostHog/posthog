import { useMemo, useState } from 'react'

import { KEY_MAPPING, keyMappingKeys } from 'lib/taxonomy'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import { Dropdown, Input, Menu, Popconfirm } from 'antd'
import { isURL } from 'lib/utils'
import { IconDeleteForever } from 'lib/lemon-ui/icons'
import './PropertiesTable.scss'
import { LemonTable, LemonTableColumns, LemonTableProps } from 'lib/lemon-ui/LemonTable'
import { CopyToClipboardInline } from '../CopyToClipboard'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { NewPropertyComponent } from 'scenes/persons/NewPropertyComponent'
import { LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { PropertyDefinitionType } from '~/types'

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
    type: PropertyDefinitionType
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
            autoComplete="off"
            autoCapitalize="off"
        />
    )
}

function ValueDisplay({
    type,
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
        propertyType = describeProperty(rootKey, type)
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
            className={clsx(
                'relative inline-flex items-center flex flex-row flex-nowrap w-fit break-all',
                canEdit ? 'editable ph-no-capture' : 'ph-no-capture'
            )}
            onClick={() => canEdit && textBasedTypes.includes(valueType) && setEditing(true)}
        >
            {!isURL(value) ? (
                valueString
            ) : (
                <Link to={value} target="_blank" className="value-link" targetBlankIcon>
                    {valueString}
                </Link>
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
                        valueComponent
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
    properties?: Record<string, any>
    sortProperties?: boolean
    searchable?: boolean
    filterable?: boolean
    /** Whether this table should be style for being embedded. Default: true. */
    embedded?: boolean
    onDelete?: (key: string) => void
    className?: string
    /* only event types are detected and so describe-able. see https://github.com/PostHog/posthog/issues/9245 */
    useDetectedPropertyType?: boolean
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
    highlightedKeys?: string[]
    type: PropertyDefinitionType
}

export function PropertiesTable({
    properties,
    rootKey,
    onEdit,
    sortProperties = false,
    searchable = false,
    filterable = false,
    embedded = true,
    nestingLevel = 0,
    onDelete,
    className,
    useDetectedPropertyType,
    tableProps,
    highlightedKeys,
    type,
}: PropertiesTableType): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const [filtered, setFiltered] = useState(false)

    if (Array.isArray(properties)) {
        return (
            <div>
                {properties.length ? (
                    properties.map((item, index) => (
                        <PropertiesTable
                            key={index}
                            type={type}
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

    const objectProperties = useMemo(() => {
        if (!properties || !(properties instanceof Object)) {
            return []
        }
        let entries = Object.entries(properties)
        if (searchTerm) {
            const normalizedSearchTerm = searchTerm.toLowerCase()
            entries = entries.filter(([key, value]) => {
                const label = KEY_MAPPING.event[key]?.label?.toLowerCase()
                return (
                    key.toLowerCase().includes(normalizedSearchTerm) ||
                    (label && label.includes(normalizedSearchTerm)) ||
                    JSON.stringify(value).toLowerCase().includes(normalizedSearchTerm)
                )
            })
        }

        if (filterable && filtered) {
            entries = entries.filter(([key]) => !key.startsWith('$') && !keyMappingKeys.includes(key))
        }

        if (sortProperties) {
            entries.sort(([aKey], [bKey]) => {
                if (highlightedKeys) {
                    const aHighlightValue = highlightedKeys.includes(aKey) ? 0 : 1
                    const bHighlightValue = highlightedKeys.includes(bKey) ? 0 : 1
                    if (aHighlightValue !== bHighlightValue) {
                        return aHighlightValue - bHighlightValue
                    }
                }

                if (aKey.startsWith('$') && !bKey.startsWith('$')) {
                    return 1
                } else if (!aKey.startsWith('$') && bKey.startsWith('$')) {
                    return -1
                }
                return aKey.localeCompare(bKey)
            })
        } else if (highlightedKeys) {
            entries.sort(([aKey], [bKey]) => {
                const aHighlightValue = highlightedKeys.includes(aKey) ? 0 : 1
                const bHighlightValue = highlightedKeys.includes(bKey) ? 0 : 1
                return aHighlightValue - bHighlightValue
            })
        }
        return entries
    }, [properties, sortProperties, searchTerm, filtered])

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
                            type={type}
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

        columns.push({
            key: 'copy',
            title: '',
            width: 0,
            render: function Copy(_, item: any): JSX.Element | false {
                if (Array.isArray(item[1]) || item[1] instanceof Object) {
                    return false
                }
                return (
                    <CopyToClipboardInline
                        description="property value"
                        explicitValue={item[1]}
                        selectable
                        isValueSensitive
                        style={{ verticalAlign: 'middle' }}
                    />
                )
            },
        })

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

        return (
            <>
                {(searchable || filterable) && (
                    <div className="flex justify-between items-center gap-2 mb-2">
                        <span className="flex justify-between gap-2">
                            {searchable && (
                                <LemonInput
                                    type="search"
                                    placeholder="Search for property keys and values"
                                    value={searchTerm || ''}
                                    onChange={setSearchTerm}
                                />
                            )}

                            {filterable && (
                                <LemonCheckbox
                                    checked={filtered}
                                    label="Hide PostHog properties"
                                    bordered
                                    onChange={setFiltered}
                                />
                            )}
                        </span>

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
                    emptyState={
                        <>
                            {filtered || searchTerm ? (
                                <span className="flex gap-2">
                                    <span>No properties found</span>
                                    <LemonButton
                                        noPadding
                                        onClick={() => {
                                            setSearchTerm('')
                                            setFiltered(false)
                                        }}
                                    >
                                        Clear filters
                                    </LemonButton>
                                </span>
                            ) : (
                                'No properties set yet'
                            )}
                        </>
                    }
                    inset={nestingLevel > 0}
                    onRow={(record) =>
                        highlightedKeys?.includes(record[0])
                            ? {
                                  style: { background: 'var(--mark)' },
                              }
                            : {}
                    }
                    {...tableProps}
                />
            </>
        )
    }
    // if none of above, it's a value
    return (
        <ValueDisplay
            type={type}
            value={properties}
            rootKey={rootKey}
            onEdit={onEdit}
            nestingLevel={nestingLevel}
            useDetectedPropertyType={useDetectedPropertyType}
        />
    )
}
