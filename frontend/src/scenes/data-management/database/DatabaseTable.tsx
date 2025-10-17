import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton, LemonSelect, Spinner, lemonToast } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DatabaseSchemaTable, DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

interface DatabaseTableProps {
    table: string
    tables: DatabaseSchemaTable[]
    inEditSchemaMode: boolean
    schemaOnChange?: (columnKey: string, columnType: DatabaseSerializedFieldType) => void
}

const nonEditableSchemaTypes = [
    'lazy_table',
    'virtual_table',
    'field_traverser',
    'expression',
    'view',
    'materialized_view',
] as const
type NonEditableSchemaTypes = Extract<DatabaseSerializedFieldType, (typeof nonEditableSchemaTypes)[number]>
const editSchemaOptions: Record<Exclude<DatabaseSerializedFieldType, NonEditableSchemaTypes>, string> = {
    integer: 'Integer',
    float: 'Float',
    decimal: 'Decimal',
    string: 'String',
    datetime: 'DateTime',
    date: 'Date',
    boolean: 'Boolean',
    array: 'Array',
    json: 'JSON',
    unknown: 'Unknown',
}
const editSchemaOptionsAsArray = Object.keys(editSchemaOptions).map((n) => ({ value: n, label: editSchemaOptions[n] }))

const isNonEditableSchemaType = (schemaType: unknown): schemaType is NonEditableSchemaTypes => {
    return typeof schemaType === 'string' && nonEditableSchemaTypes.includes(schemaType as NonEditableSchemaTypes)
}
const JoinsMoreMenu = ({ tableName, fieldName }: { tableName: string; fieldName: string }): JSX.Element => {
    const { currentTeamId } = useValues(teamLogic)
    const { toggleEditJoinModal } = useActions(viewLinkLogic)
    const { joins, joinsLoading } = useValues(dataWarehouseJoinsLogic)
    const { loadJoins } = useActions(dataWarehouseJoinsLogic)
    const { loadDatabase } = useActions(dataWarehouseSettingsSceneLogic)

    const join = joins.find((n) => n.source_table_name === tableName && n.field_name === fieldName)

    const overlay = useCallback(
        () =>
            joinsLoading || !join ? (
                <Spinner />
            ) : (
                <>
                    <LemonButton fullWidth onClick={() => void toggleEditJoinModal(join)}>
                        Edit
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        fullWidth
                        onClick={() => {
                            void deleteWithUndo({
                                endpoint: `environments/${currentTeamId}/warehouse_view_link`,
                                object: {
                                    id: join.id,
                                    name: `${join.field_name} on ${join.source_table_name}`,
                                },
                                callback: () => {
                                    loadDatabase()
                                    loadJoins()
                                },
                            }).catch((e) => {
                                lemonToast.error(`Failed to delete warehouse view link: ${e.detail}`)
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                </>
            ),
        [joinsLoading, join] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    return <More overlay={overlay()} />
}

export function DatabaseTable({ table, tables, inEditSchemaMode, schemaOnChange }: DatabaseTableProps): JSX.Element {
    const dataSource = Object.values(tables.find(({ name }) => name === table)?.fields ?? {})
    const { dataWarehouseTables, databaseLoading } = useValues(dataWarehouseSettingsSceneLogic)

    return (
        <LemonTable
            dataSource={dataSource}
            loading={databaseLoading}
            disableTableWhileLoading={false}
            columns={[
                {
                    title: 'Column',
                    key: 'key',
                    dataIndex: 'name',
                    render: function RenderColumn(column) {
                        return <code>{column}</code>
                    },
                },
                {
                    title: 'Type',
                    key: 'type',
                    dataIndex: 'type',
                    render: function RenderType(_, { name, type, schema_valid }) {
                        if (inEditSchemaMode && !isNonEditableSchemaType(type)) {
                            return (
                                <LemonSelect
                                    options={editSchemaOptionsAsArray}
                                    value={type}
                                    onChange={(newValue) => {
                                        if (schemaOnChange) {
                                            schemaOnChange(name, newValue as DatabaseSerializedFieldType)
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

                        const tagType: LemonTagType = schema_valid ? 'default' : 'danger'

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
                        } else if (table == 'events' && type == 'json' && field.name == 'properties') {
                            return <Link to={urls.propertyDefinitions('event')}>Manage event properties</Link>
                        } else if (table == 'persons' && type == 'json' && field.name == 'properties') {
                            return <Link to={urls.propertyDefinitions('person')}>Manage person properties</Link>
                        }

                        if (!field.schema_valid && !inEditSchemaMode) {
                            return (
                                <>
                                    <code>{field.name}</code> can't be parsed as a <code>{field.type}</code>. It will
                                    not be queryable until this is fixed.
                                </>
                            )
                        }

                        return ''
                    },
                },
                {
                    width: 0,
                    dataIndex: 'type',
                    render: function RenderActions(_, data) {
                        if (data.type === 'view') {
                            return <JoinsMoreMenu tableName={table} fieldName={data.name} />
                        }

                        if (data.type === 'lazy_table' && data.table) {
                            const isJoiningTableExternalTable = !!dataWarehouseTables.find((n) => n.name === data.table)
                            const isSourceExternalTable = !!dataWarehouseTables.find((n) => n.name === table)

                            if (isJoiningTableExternalTable || isSourceExternalTable) {
                                return <JoinsMoreMenu tableName={table} fieldName={data.name} />
                            }
                        }

                        return null
                    },
                },
            ]}
        />
    )
}
