import './PropertiesTable.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconPencil, IconTrash, IconWarning } from '@posthog/icons'
import { LemonCheckbox, LemonDialog, LemonInput, LemonMenu, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumns, LemonTableProps } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { isObject, isURL } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { NewProperty } from 'scenes/persons/NewProperty'
import { urls } from 'scenes/urls'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    KNOWN_PROMOTED_PROPERTY_PARENTS,
    POSTHOG_EVENT_PROMOTED_PROPERTIES,
    isPostHogProperty,
} from '~/taxonomy/taxonomy'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import { PropertyDefinitionType, PropertyType } from '~/types'

import { CopyToClipboardInline } from '../CopyToClipboard'
import { JSONViewer } from '../JSONViewer'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from '../PropertyFilters/utils'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'

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
    initialValue,
    onChange,
}: {
    initialValue: any
    onChange: (newValue: any) => void
}): JSX.Element {
    const [value, setValue] = useState(initialValue)

    return (
        <LemonInput
            autoFocus
            value={value}
            onChange={setValue}
            onBlur={() => onChange(initialValue)}
            onPressEnter={() => onChange(value)}
            autoComplete="off"
            autoCapitalize="off"
            size="xsmall"
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
    const canEdit = rootKey && !PROPERTY_KEYS.includes(rootKey) && (!nestingLevel || nestingLevel <= 1) && onEdit

    const textBasedTypes = ['string', 'number', 'bigint'] // Values that are edited with a text box
    const boolNullTypes = ['boolean', 'null'] // Values that are edited with the boolNullSelect dropdown

    let propertyType
    if (rootKey && useDetectedPropertyType) {
        propertyType = describeProperty(rootKey, type)
    }
    const valueType: Type = value === null ? 'null' : typeof value // typeof null returns 'object' ¯\_(ツ)_/¯

    const valueString: string = value === null ? 'null' : String(value) // typeof null returns 'object' ¯\_(ツ)_/¯

    const handleValueChange = (newValue: any): void => {
        setEditing(false)
        if (rootKey !== undefined && onEdit && newValue != value) {
            onEdit(rootKey, newValue, value)
        }
    }

    const valueComponent = (
        <span
            className={clsx(
                'relative inline-flex gap-1 items-center flex flex-row flex-nowrap w-fit break-all',
                canEdit ? 'editable ph-no-capture' : 'ph-no-capture'
            )}
            onClick={() => canEdit && textBasedTypes.includes(valueType) && setEditing(true)}
        >
            {!isURL(value) ? (
                <span>{valueString}</span>
            ) : (
                <Link to={value} target="_blank" className="value-link" targetBlankIcon>
                    {valueString}
                </Link>
            )}
            {canEdit && <IconPencil />}
        </span>
    )

    const isTypeMismatched =
        (propertyType === PropertyType.String && valueType === 'number') ||
        (propertyType === PropertyType.Numeric && valueType === 'string')

    return (
        <div className="properties-table-value">
            {!editing ? (
                <>
                    {canEdit && boolNullTypes.includes(valueType) ? (
                        <LemonMenu
                            items={[
                                {
                                    label: 'true',
                                    onClick: () => handleValueChange(true),
                                },
                                {
                                    label: 'false',
                                    onClick: () => handleValueChange(false),
                                },
                                {
                                    label: 'null',
                                    onClick: () => handleValueChange(null),
                                    status: 'danger',
                                },
                            ]}
                        >
                            {valueComponent}
                        </LemonMenu>
                    ) : (
                        valueComponent
                    )}
                    <Tooltip
                        title={
                            isTypeMismatched
                                ? `This value is of type "${valueType}", which is incompatible with the property's defined type "${propertyType}". Click to update the property definition.`
                                : null
                        }
                        delayMs={0}
                    >
                        <Link
                            to={
                                isTypeMismatched
                                    ? combineUrl(urls.propertyDefinitions(), { property: rootKey }).url
                                    : undefined
                            }
                        >
                            <LemonTag
                                className="ml-1 font-mono uppercase"
                                type={isTypeMismatched ? 'danger' : 'muted'}
                                icon={isTypeMismatched ? <IconWarning /> : undefined}
                            >
                                {valueType}
                                {isTypeMismatched && ' (mismatched)'}
                            </LemonTag>
                        </Link>
                    </Tooltip>
                </>
            ) : (
                <EditTextValueComponent initialValue={value} onChange={handleValueChange} />
            )}
        </div>
    )
}

interface PropertiesTableType extends BasePropertyType {
    properties?: Record<string, any> | Array<Record<string, any>>
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
    /**
     * The container for these properties e.g. the event name of the event the properties are on
     * Can be used for e.g. to promote particular properties when sorting the properties
     */
    parent?: KNOWN_PROMOTED_PROPERTY_PARENTS
}

export function PropertiesTable({
    properties,
    rootKey,
    onEdit,
    sortProperties = true,
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
    parent,
}: PropertiesTableType): JSX.Element {
    const [searchTerm, setSearchTerm] = useState('')
    const { hidePostHogPropertiesInTable, hideNullValues } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable, setHideNullValues } = useActions(userPreferencesLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const objectProperties = useMemo(() => {
        if (!properties || Array.isArray(properties) || !isObject(properties)) {
            return []
        }

        let entries = Object.entries(properties)
        if (sortProperties) {
            entries = entries.sort((a, b) => {
                // if this is a posthog property we want to sort by its label
                const propertyTypeMap: Record<PropertyDefinitionType, TaxonomicFilterGroupType> = {
                    [PropertyDefinitionType.Event]: TaxonomicFilterGroupType.EventProperties,
                    [PropertyDefinitionType.EventMetadata]: TaxonomicFilterGroupType.EventMetadata,
                    [PropertyDefinitionType.RevenueAnalytics]: TaxonomicFilterGroupType.RevenueAnalyticsProperties,
                    [PropertyDefinitionType.Person]: TaxonomicFilterGroupType.PersonProperties,
                    [PropertyDefinitionType.Group]: TaxonomicFilterGroupType.GroupsPrefix,
                    [PropertyDefinitionType.Session]: TaxonomicFilterGroupType.SessionProperties,
                    [PropertyDefinitionType.LogEntry]: TaxonomicFilterGroupType.LogEntries,
                    [PropertyDefinitionType.Meta]: TaxonomicFilterGroupType.Metadata,
                    [PropertyDefinitionType.Resource]: TaxonomicFilterGroupType.Resources,
                    [PropertyDefinitionType.Log]: TaxonomicFilterGroupType.LogAttributes,
                    [PropertyDefinitionType.FlagValue]: TaxonomicFilterGroupType.FeatureFlags,
                }

                const propertyType = propertyTypeMap[type] || TaxonomicFilterGroupType.EventProperties

                const left = getCoreFilterDefinition(a[0], propertyType)?.label || a[0]
                const right = getCoreFilterDefinition(b[0], propertyType)?.label || b[0]

                if (left < right) {
                    return -1
                }
                if (left > right) {
                    return 1
                }
                return 0
            })
            if (parent) {
                const promotedProperties = POSTHOG_EVENT_PROMOTED_PROPERTIES[parent]
                const promotedItems = promotedProperties?.length
                    ? entries
                          .filter(([key]) => promotedProperties.includes(key))
                          .sort((a, b) => promotedProperties.indexOf(a[0]) - promotedProperties.indexOf(b[0]))
                    : []
                const nonPromotedItems = promotedProperties?.length
                    ? entries.filter(([key]) => !promotedProperties.includes(key))
                    : entries
                entries = [...promotedItems, ...nonPromotedItems]
            }
        }

        if (searchTerm) {
            const normalizedSearchTerm = searchTerm.toLowerCase()
            entries = entries.filter(([key, value]) => {
                const label = CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[key]?.label?.toLowerCase()
                return (
                    key.toLowerCase().includes(normalizedSearchTerm) ||
                    (label && label.includes(normalizedSearchTerm)) ||
                    JSON.stringify(value).toLowerCase().includes(normalizedSearchTerm)
                )
            })
        }

        if (filterable) {
            entries = entries.filter(([key, value]) => {
                if (hideNullValues && value === null) {
                    return false
                }
                if (hidePostHogPropertiesInTable) {
                    return !isPostHogProperty(key, isCloudOrDev)
                }
                return true
            })
        }

        if (highlightedKeys) {
            entries.sort(([aKey], [bKey]) => {
                const aHighlightValue = highlightedKeys.includes(aKey) ? 0 : 1
                const bHighlightValue = highlightedKeys.includes(bKey) ? 0 : 1
                return aHighlightValue - bHighlightValue
            })
        }
        return entries
    }, [properties, sortProperties, searchTerm, hidePostHogPropertiesInTable, hideNullValues]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (Array.isArray(properties)) {
        return (
            <div>
                {properties.length ? (
                    <LemonTable
                        columns={[
                            {
                                key: 'key',
                                title: 'Index',
                                render: function Key(_, item: any): JSX.Element {
                                    return <div className="properties-table-key">{item[0]}</div>
                                },
                            },
                            {
                                key: 'value',
                                title: (
                                    <div className="flex justify-between w-full">
                                        <div>Value</div>
                                        <LemonTag type="muted" className="font-mono uppercase">
                                            array
                                        </LemonTag>
                                    </div>
                                ),
                                fullWidth: true,
                                render: function Value(_, item: any): JSX.Element {
                                    const arrayItem = item[1]
                                    const isComplexStructure =
                                        Array.isArray(arrayItem) || (isObject(arrayItem) && arrayItem !== null)
                                    if (!featureFlags[FEATURE_FLAGS.TOGGLE_PROPERTY_ARRAYS]) {
                                        return (
                                            <PropertiesTable
                                                type={type}
                                                properties={item[1]}
                                                nestingLevel={nestingLevel + 1}
                                                useDetectedPropertyType={
                                                    ['$set', '$set_once'].some((s) => s === rootKey)
                                                        ? false
                                                        : useDetectedPropertyType
                                                }
                                            />
                                        )
                                    }

                                    if (isComplexStructure) {
                                        return <JSONViewer src={arrayItem} collapsed={true} />
                                    }

                                    return (
                                        <ValueDisplay
                                            type={type}
                                            value={arrayItem}
                                            nestingLevel={nestingLevel + 1}
                                            useDetectedPropertyType={
                                                ['$set', '$set_once'].some((s) => s === rootKey)
                                                    ? false
                                                    : useDetectedPropertyType
                                            }
                                        />
                                    )
                                },
                            },
                        ]}
                        dataSource={properties.map((item, index) => [index, item])}
                    />
                ) : (
                    <LemonTag type="muted" className="font-mono uppercase">
                        Array (empty)
                    </LemonTag>
                )}
            </div>
        )
    }

    if (properties instanceof Object) {
        const columns: LemonTableColumns<Record<string, any>> = [
            {
                key: 'key',
                title: 'Key',
                // Minimize the width of the key column when nested
                style: nestingLevel > 0 ? { width: '0px' } : undefined,
                render: function Key(_, item: any): JSX.Element {
                    return (
                        <div className="properties-table-key">
                            <PropertyKeyInfo
                                value={item[0]}
                                type={
                                    rootKey && type === 'event' && ['$set', '$set_once'].includes(rootKey)
                                        ? TaxonomicFilterGroupType.PersonProperties
                                        : PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[type]
                                }
                            />
                        </div>
                    )
                },
                sorter: (a, b) => String(a[0]).localeCompare(String(b[0])),
            },
            {
                key: 'value',
                title: 'Value',
                render: function Value(_, item: any): JSX.Element {
                    const isComplexStructure = Array.isArray(item[1]) || (isObject(item[1]) && item[1] !== null)

                    if (isComplexStructure && featureFlags[FEATURE_FLAGS.TOGGLE_PROPERTY_ARRAYS]) {
                        return <JSONViewer src={item[1]} collapsed={true} />
                    }
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
                return (
                    <CopyToClipboardInline
                        description="property value"
                        explicitValue={typeof item[1] === 'object' ? JSON.stringify(item[1]) : String(item[1])}
                        selectable
                        isValueSensitive
                        style={{ verticalAlign: 'middle' }}
                    />
                )
            },
        })

        if (onDelete && nestingLevel === 0) {
            const onClickDelete = (property: string): void => {
                LemonDialog.open({
                    title: (
                        <>
                            Are you sure you want to delete property <code>{property}</code>?
                        </>
                    ),
                    description: 'This cannot be undone',
                    primaryButton: {
                        type: 'primary',
                        status: 'danger',
                        onClick: () => onDelete(property),
                        children: 'Delete',
                    },
                })
            }

            columns.push({
                key: 'delete',
                title: '',
                width: 0,
                render: function Delete(_, item: any): JSX.Element | false {
                    return (
                        !PROPERTY_KEYS.includes(item[0]) &&
                        !String(item[0]).startsWith('$initial_') && (
                            <LemonButton
                                icon={<IconTrash />}
                                status="danger"
                                size="small"
                                onClick={() => onClickDelete(item[0])}
                            />
                        )
                    )
                },
            })
        }

        return (
            <>
                {(searchable || filterable) && (
                    <div className="flex items-center justify-between gap-2 mb-2">
                        <span className="flex justify-between gap-2">
                            {searchable && (
                                <LemonInput
                                    type="search"
                                    placeholder="Search property keys and values"
                                    value={searchTerm || ''}
                                    onChange={setSearchTerm}
                                    className="w-64 max-w-full"
                                />
                            )}

                            {filterable && (
                                <>
                                    <LemonCheckbox
                                        checked={hidePostHogPropertiesInTable}
                                        label="Hide PostHog properties"
                                        bordered
                                        onChange={setHidePostHogPropertiesInTable}
                                    />

                                    <LemonCheckbox
                                        checked={hideNullValues}
                                        label="Hide null values"
                                        bordered
                                        onChange={setHideNullValues}
                                    />
                                </>
                            )}
                        </span>

                        {onEdit && <NewProperty onSave={onEdit} />}
                    </div>
                )}

                <LemonTable
                    columns={columns}
                    showHeader={!embedded}
                    rowKey="0"
                    embedded={embedded}
                    dataSource={objectProperties}
                    className={className}
                    emptyState={
                        <>
                            {hidePostHogPropertiesInTable || searchTerm ? (
                                <span className="flex gap-2">
                                    <span>No properties found</span>
                                    <LemonButton
                                        noPadding
                                        onClick={() => {
                                            setSearchTerm('')
                                            setHidePostHogPropertiesInTable(false)
                                            setHideNullValues(false)
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

    if (properties === undefined) {
        return <div className="px-4 py-2">No defined properties</div>
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
