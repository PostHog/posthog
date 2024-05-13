import { LemonSelect } from '@posthog/lemon-ui'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { DatabaseTableListRow } from 'scenes/data-warehouse/types'
import { ViewLinkDeleteButton } from 'scenes/data-warehouse/ViewLinkModal'
import { urls } from 'scenes/urls'

import { DatabaseSerializedFieldType } from '~/queries/schema'

interface DatabaseTableProps {
    table: string
    tables: DatabaseTableListRow[]
    inEditSchemaMode: boolean
    schemaOnChange?: (columnKey: string, columnType: DatabaseSerializedFieldType) => void
}

const nonEditableSchemaTypes = ['lazy_table', 'virtual_table', 'field_traverser', 'expression', 'view'] as const
type NonEditableSchemaTypes = Extract<DatabaseSerializedFieldType, (typeof nonEditableSchemaTypes)[number]>
const editSchemaOptions: Record<Exclude<DatabaseSerializedFieldType, NonEditableSchemaTypes>, string> = {
    integer: 'Integer',
    float: 'Float',
    string: 'String',
    datetime: 'DateTime',
    date: 'Date',
    boolean: 'Boolean',
    array: 'Array',
    json: 'JSON',
}
const editSchemaOptionsAsArray = Object.keys(editSchemaOptions).map((n) => ({ value: n, label: editSchemaOptions[n] }))

const isNonEditableSchemaType = (schemaType: unknown): schemaType is NonEditableSchemaTypes => {
    return typeof schemaType === 'string' && nonEditableSchemaTypes.includes(schemaType as NonEditableSchemaTypes)
}

export function DatabaseTable({ table, tables, inEditSchemaMode, schemaOnChange }: DatabaseTableProps): JSX.Element {
    const dataSource = tables.find(({ name }) => name === table)?.columns ?? []

    return (
        <LemonTable
            dataSource={dataSource}
            columns={[
                {
                    title: 'Column',
                    key: 'key',
                    dataIndex: 'key',
                    render: function RenderColumn(column) {
                        return <code>{column}</code>
                    },
                },
                {
                    title: 'Type',
                    key: 'type',
                    dataIndex: 'type',
                    render: function RenderType(_, { key, type, schema_valid }) {
                        if (inEditSchemaMode && !isNonEditableSchemaType(type)) {
                            return (
                                <LemonSelect
                                    options={editSchemaOptionsAsArray}
                                    value={type}
                                    onChange={(newValue) => {
                                        if (schemaOnChange) {
                                            schemaOnChange(key, newValue as DatabaseSerializedFieldType)
                                        }
                                    }}
                                />
                            )
                        }

                        if (type === 'virtual_table') {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Virtual Table
                                </LemonTag>
                            )
                        } else if (type === 'lazy_table') {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Reference
                                </LemonTag>
                            )
                        } else if (type === 'field_traverser') {
                            return (
                                <LemonTag type="default" className="uppercase">
                                    Expression
                                </LemonTag>
                            )
                        }

                        const tagType: LemonTagType = schema_valid ? 'success' : 'danger'

                        return (
                            <LemonTag type={tagType} className="uppercase">
                                {type}
                            </LemonTag>
                        )
                    },
                },
                {
                    title: 'Info',
                    key: 'info',
                    dataIndex: 'type',
                    render: function RenderInfo(type, field) {
                        if (type === 'virtual_table' || type === 'view') {
                            return (
                                <>
                                    Fields: <code>{(field as any).fields.join(', ')}</code>
                                </>
                            )
                        } else if (type === 'lazy_table') {
                            return (
                                <>
                                    To table: <code>{String((field as any).table)}</code>
                                </>
                            )
                        } else if (type === 'field_traverser' && Array.isArray((field as any).chain)) {
                            return <code>{(field as any).chain.join('.')}</code>
                        } else if (table == 'events' && type == 'json' && field.key == 'properties') {
                            return <Link to={urls.propertyDefinitions('event')}>Manage event properties</Link>
                        } else if (table == 'persons' && type == 'json' && field.key == 'properties') {
                            return <Link to={urls.propertyDefinitions('person')}>Manage person properties</Link>
                        }

                        if (!field.schema_valid && !inEditSchemaMode) {
                            return (
                                <>
                                    <code>{field.key}</code> can't be parsed as a <code>{field.type}</code>. It will not
                                    be queryable until this is fixed.
                                </>
                            )
                        }

                        return ''
                    },
                },
                {
                    title: 'Actions',
                    key: 'actions',
                    dataIndex: 'type',
                    render: function RenderActions(_, data) {
                        if (data.type === 'view') {
                            return (
                                <div className="flex flex-row justify-between">
                                    <ViewLinkDeleteButton table={table} column={data.key} />
                                </div>
                            )
                        }

                        return null
                    },
                },
            ]}
        />
    )
}
