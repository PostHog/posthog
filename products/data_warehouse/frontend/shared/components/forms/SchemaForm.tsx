import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconInfo, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { pluralize } from 'lib/utils/strings'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from 'products/data_warehouse/frontend/utils'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'
import { ColumnSelectionPicker } from '../../../scenes/SourceScene/tabs/ColumnSelectionModal'
import { RowFilterEditor } from '../../../scenes/SourceScene/tabs/RowFilterEditor'
import { splitQualifiedTableName } from './schemaGroupingUtils'
import { SyncMethodForm } from './SyncMethodForm'

export function getDirectQuerySelectionDescription(selectedSchema?: string | null): string {
    const normalizedSchema = selectedSchema?.trim()

    if (normalizedSchema) {
        return `Query selected Postgres tables from within PostHog. Tables stay in the source database and are not synced into the data warehouse. You can't join data from these tables with other data in the PostHog warehouse. Choose which tables from the "${normalizedSchema}" schema should be queryable.`
    }

    return "Query selected Postgres tables from within PostHog. Tables stay in the source database and are not synced into the data warehouse. You can't join data from these tables with other data in the PostHog warehouse. Enable each schema to choose which tables should be queryable."
}

function getSchemaSelectionState(tables: ExternalDataSourceSyncSchema[]): boolean | 'indeterminate' {
    const enabledCount = tables.filter((table) => table.should_sync).length

    if (enabledCount === 0) {
        return false
    }

    if (enabledCount === tables.length) {
        return true
    }

    return 'indeterminate'
}

export default function SchemaForm(): JSX.Element {
    const containerRef = useFloatingContainer()
    const {
        toggleSchemaShouldSync,
        toggleAllTables,
        openSyncMethodModal,
        toggleSchemaGroup,
        setExpandedSchemaGroupKeys,
        setSchemaNameFilter,
        setSchemaSyncedColumns,
        setSchemaRowFilters,
    } = useActions(sourceWizardLogic)
    const [columnSelectionSchema, setColumnSelectionSchema] = useState<ExternalDataSourceSyncSchema | null>(null)
    const {
        databaseSchema,
        filteredDatabaseSchema,
        schemaNameFilter,
        suggestedTablesMap,
        isDirectQueryMode,
        tablesAllToggledOn,
        source,
        selectedConnector,
        groupedDatabaseSchema,
        expandedSchemaGroupKeys,
    } = useValues(sourceWizardLogic)

    const onClickCheckbox = (schema: ExternalDataSourceSyncSchema, checked: boolean): void => {
        if (schema.permission_error) {
            return
        }
        if (!isDirectQueryMode && schema.sync_type === null) {
            openSyncMethodModal(schema)
            return
        }
        toggleSchemaShouldSync(schema, checked)
    }

    const shouldShowSyncColumns = !isDirectQueryMode
    const shouldShowColumnSelection = !isDirectQueryMode && !!selectedConnector?.supportsColumnSelection

    // scroll to top of container
    useEffect(() => {
        containerRef?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
    }, [containerRef])

    const showRows = databaseSchema.some((schema) => schema.rows != null)
    const hasManySchemas = databaseSchema.length > 10

    const warehouseColumns = [
        {
            width: 0,
            key: 'enabled',
            render: function RenderEnabled(_: unknown, schema: ExternalDataSourceSyncSchema) {
                return (
                    <LemonCheckbox
                        checked={schema.should_sync}
                        disabledReason={schema.permission_error ?? undefined}
                        onChange={(checked) => onClickCheckbox(schema, checked)}
                    />
                )
            },
        },
        {
            title: 'Table',
            key: 'table',
            render: function RenderTable(_: unknown, schema: ExternalDataSourceSyncSchema) {
                const isSuggested = suggestedTablesMap[schema.table] !== undefined
                const tooltip =
                    suggestedTablesMap[schema.table] ?? 'This table is suggested to be enabled for this source'
                const isUnavailable = !!schema.permission_error

                return (
                    <div className="flex items-center gap-2">
                        <span
                            className={`font-mono ${
                                isUnavailable ? 'text-muted-alt line-through cursor-not-allowed' : 'cursor-pointer'
                            }`}
                            onClick={() => {
                                if (isUnavailable) {
                                    return
                                }
                                onClickCheckbox(schema, !schema.should_sync)
                            }}
                        >
                            {schema.label || schema.table}
                        </span>
                        {schema.description && (
                            <Tooltip title={schema.description}>
                                <IconInfo className="text-muted-alt text-base" />
                            </Tooltip>
                        )}
                        {isUnavailable && (
                            <Tooltip
                                title={`Source credentials cannot read this table: ${schema.permission_error}. Grant the missing scope in your source provider and reconnect.`}
                                placement="top"
                            >
                                <LemonTag type="warning" className="cursor-help">
                                    <IconWarning className="mr-1" />
                                    Permission missing
                                </LemonTag>
                            </Tooltip>
                        )}
                        {isSuggested && (
                            <Tooltip title={tooltip} placement="top">
                                <LemonTag type="primary" className="cursor-help">
                                    Suggested
                                </LemonTag>
                            </Tooltip>
                        )}
                        {schema.rls_warning && (
                            <Tooltip title={schema.rls_warning} placement="top">
                                <LemonTag type="warning" className="cursor-help">
                                    <IconWarning className="mr-1" />
                                    RLS may hide rows
                                </LemonTag>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Rows',
            key: 'rows',
            isHidden: !databaseSchema.some((schema) => schema.rows),
            render: function RenderRows(_: unknown, schema: ExternalDataSourceSyncSchema) {
                if (schema.rows != null) {
                    return schema.rows
                }
                return (
                    <Tooltip title="Row count was skipped for this table because counting would require a full scan (e.g. plain views, Memory/Buffer/Log-engine tables, or Kafka/URL table functions). The table can still be synced — we just don't know its size up front.">
                        <span className="text-muted-alt cursor-help">Skipped</span>
                    </Tooltip>
                )
            },
        },
        {
            key: 'sync_field',
            title: 'Sync field',
            align: 'right' as const,
            tooltip:
                'Incremental and append-only refresh methods key on a unique field to determine the most up-to-date data.',
            isHidden: !shouldShowSyncColumns || !databaseSchema.some((schema) => schema.sync_type),
            render: function RenderSyncType(_: unknown, schema: ExternalDataSourceSyncSchema) {
                if (isDirectQueryMode) {
                    return (
                        <span className="text-xs text-muted-foreground">
                            Only selected tables are queryable in direct mode
                        </span>
                    )
                }
                if (!schema.incremental_available && !schema.append_available) {
                    return <span className="text-xs text-muted-foreground">Incremental sync not supported</span>
                }

                if (schema.sync_type === 'webhook') {
                    return <LemonTag type="success">Webhook</LemonTag>
                }

                if (schema.sync_type !== 'full_refresh' && schema.sync_type !== null && schema.incremental_field) {
                    const field = schema.incremental_fields.find((f) => f.field == schema.incremental_field) ?? null

                    if (field) {
                        return (
                            <div className="flex items-center justify-end">
                                {field.nullable && (
                                    <Tooltip
                                        title={`This field is nullable. Any rows where ${field.label} is null will not be synced.`}
                                    >
                                        <IconWarning className="mr-1 text-warning text-xl" />
                                    </Tooltip>
                                )}
                                <span className="leading-5">{field.label}</span>
                                <LemonTag className="ml-2" type="success">
                                    {field.type}
                                </LemonTag>
                            </div>
                        )
                    }
                }

                return <span className="text-xs text-muted-foreground">No sync field selected</span>
            },
        },
        {
            key: 'primary_key',
            title: 'Primary key',
            align: 'right' as const,
            tooltip:
                'The column(s) used to uniquely identify rows for deduplication during incremental syncs. Auto-detected if not set.',
            isHidden: !shouldShowSyncColumns || !databaseSchema.some((schema) => schema.sync_type === 'incremental'),
            render: function RenderPrimaryKey(_: unknown, schema: ExternalDataSourceSyncSchema) {
                if (schema.sync_type !== 'incremental') {
                    return <span className="text-xs text-muted-foreground">No primary key selected</span>
                }

                if (!schema.primary_key_columns || schema.primary_key_columns.length === 0) {
                    const detected = schema.detected_primary_keys
                    if (detected && detected.length > 0) {
                        return (
                            <div className="flex items-center justify-end gap-1 flex-wrap">
                                {detected.map((col) => (
                                    <LemonTag key={col} type="muted">
                                        {col}
                                    </LemonTag>
                                ))}
                            </div>
                        )
                    }

                    return <span className="text-xs text-muted-foreground">None detected</span>
                }

                return (
                    <div className="flex items-center justify-end gap-1 flex-wrap">
                        {schema.primary_key_columns.map((col) => (
                            <LemonTag key={col} type="default">
                                {col}
                            </LemonTag>
                        ))}
                    </div>
                )
            },
        },
        {
            key: 'sync_type',
            title: 'Sync method',
            align: 'right' as const,
            isHidden: !shouldShowSyncColumns,
            tooltip:
                'Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync',
            render: function RenderSyncType(_: unknown, schema: ExternalDataSourceSyncSchema) {
                if (isDirectQueryMode) {
                    return (
                        <span className="text-xs text-muted-foreground">
                            Only selected tables are queryable in direct mode
                        </span>
                    )
                }
                if (!schema.sync_type) {
                    return (
                        <div className="justify-end flex">
                            <LemonButton
                                className="my-1"
                                type="primary"
                                onClick={() => openSyncMethodModal(schema)}
                                size="small"
                                disabledReason={schema.permission_error ?? undefined}
                            >
                                Configure
                            </LemonButton>
                        </div>
                    )
                }
                return (
                    <div className="justify-end flex">
                        <LemonButton
                            className="my-1"
                            size="small"
                            type="secondary"
                            onClick={() => openSyncMethodModal(schema)}
                            disabledReason={
                                schema.permission_error ??
                                (!schema.incremental_available && !schema.append_available && !schema.supports_webhooks
                                    ? 'Full refresh is the only supported sync method for this table'
                                    : undefined)
                            }
                        >
                            {SyncTypeLabelMap[schema.sync_type]}
                        </LemonButton>
                    </div>
                )
            },
        },
        {
            key: 'columns',
            title: 'Columns',
            align: 'right' as const,
            isHidden: !shouldShowColumnSelection,
            tooltip:
                'Pick a subset of columns to sync. Primary keys and the active incremental field are always retained.',
            render: function RenderColumns(_: unknown, schema: ExternalDataSourceSyncSchema) {
                if (schema.available_columns.length === 0) {
                    return <span className="text-xs text-muted-foreground">—</span>
                }
                const synced = schema.enabled_columns
                const alwaysRetained = new Set<string>([
                    ...(schema.primary_key_columns ?? []),
                    ...(schema.incremental_field ? [schema.incremental_field] : []),
                ])
                const syncedCount = synced
                    ? new Set([...synced, ...alwaysRetained]).size
                    : schema.available_columns.length
                const summary = !synced
                    ? `All ${schema.available_columns.length}`
                    : `${syncedCount} of ${schema.available_columns.length}`
                return (
                    <div className="justify-end flex">
                        <LemonButton
                            className="my-1"
                            size="small"
                            type="secondary"
                            onClick={() => setColumnSelectionSchema(schema)}
                            disabledReason={schema.permission_error ?? undefined}
                        >
                            {summary}
                        </LemonButton>
                    </div>
                )
            },
        },
    ]

    return (
        <>
            <div className="flex flex-col gap-2 flex-1 min-h-0">
                {hasManySchemas && (
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Filter tables"
                            size="small"
                            value={schemaNameFilter}
                            onChange={setSchemaNameFilter}
                        />
                        <span className="text-muted text-sm">
                            {schemaNameFilter
                                ? `${filteredDatabaseSchema.length} of ${pluralize(
                                      databaseSchema.length,
                                      'table',
                                      'tables'
                                  )}`
                                : pluralize(databaseSchema.length, 'table', 'tables')}
                        </span>
                    </div>
                )}
                <div className="flex-1 min-h-0 overflow-y-auto">
                    {isDirectQueryMode ? (
                        groupedDatabaseSchema.length > 0 ? (
                            <div className="border rounded bg-bg-light">
                                <LemonCollapse
                                    multiple
                                    embedded
                                    activeKeys={
                                        groupedDatabaseSchema.length === 1
                                            ? groupedDatabaseSchema.map((g: { schemaName: string }) => g.schemaName)
                                            : expandedSchemaGroupKeys
                                    }
                                    onChange={setExpandedSchemaGroupKeys}
                                    panels={groupedDatabaseSchema.map(({ schemaName, tables }) => {
                                        const selectedTablesCount = tables.filter((table) => table.should_sync).length

                                        return {
                                            key: schemaName,
                                            header: (
                                                <div className="flex items-center justify-between gap-3 w-full">
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        <LemonCheckbox
                                                            checked={getSchemaSelectionState(tables)}
                                                            stopPropagation
                                                            onChange={(checked) =>
                                                                toggleSchemaGroup(schemaName, checked)
                                                            }
                                                        />
                                                        <span className="font-semibold truncate">{schemaName}</span>
                                                    </div>
                                                    <span className="text-xs text-muted-alt whitespace-nowrap">
                                                        {selectedTablesCount} of {tables.length} tables queryable
                                                    </span>
                                                </div>
                                            ),
                                            content: (
                                                <div className="bg-bg-light">
                                                    <div>
                                                        {tables.map((schema) => {
                                                            const isSuggested =
                                                                suggestedTablesMap[schema.table] !== undefined
                                                            const tooltip =
                                                                suggestedTablesMap[schema.table] ??
                                                                'This table is suggested to be enabled for this source'
                                                            const { tableName } = splitQualifiedTableName(
                                                                schema.table,
                                                                source.payload.schema
                                                            )

                                                            return (
                                                                <div
                                                                    key={schema.table}
                                                                    className={`grid items-center border-b last:border-b-0 px-6 py-1 ${
                                                                        showRows
                                                                            ? 'grid-cols-[auto_minmax(0,1fr)_auto] gap-2'
                                                                            : 'grid-cols-[auto_minmax(0,1fr)] gap-2'
                                                                    }`}
                                                                >
                                                                    <LemonCheckbox
                                                                        checked={schema.should_sync}
                                                                        disabledReason={
                                                                            schema.permission_error ?? undefined
                                                                        }
                                                                        onChange={(checked) =>
                                                                            onClickCheckbox(schema, checked)
                                                                        }
                                                                    />
                                                                    <div className="flex items-center gap-2 min-w-0">
                                                                        <span
                                                                            className={`font-mono truncate ${
                                                                                schema.permission_error
                                                                                    ? 'text-muted-alt line-through cursor-not-allowed'
                                                                                    : 'cursor-pointer'
                                                                            }`}
                                                                            onClick={() => {
                                                                                if (schema.permission_error) {
                                                                                    return
                                                                                }
                                                                                onClickCheckbox(
                                                                                    schema,
                                                                                    !schema.should_sync
                                                                                )
                                                                            }}
                                                                        >
                                                                            {tableName}
                                                                        </span>
                                                                        {schema.description && (
                                                                            <Tooltip title={schema.description}>
                                                                                <IconInfo className="text-muted-alt text-base shrink-0" />
                                                                            </Tooltip>
                                                                        )}
                                                                        {schema.permission_error && (
                                                                            <Tooltip
                                                                                title={`Source credentials cannot read this table: ${schema.permission_error}. Grant the missing scope in your source provider and reconnect.`}
                                                                                placement="top"
                                                                            >
                                                                                <LemonTag
                                                                                    type="warning"
                                                                                    className="cursor-help shrink-0"
                                                                                >
                                                                                    <IconWarning className="mr-1" />
                                                                                    Permission missing
                                                                                </LemonTag>
                                                                            </Tooltip>
                                                                        )}
                                                                        {isSuggested && (
                                                                            <Tooltip title={tooltip} placement="top">
                                                                                <LemonTag
                                                                                    type="primary"
                                                                                    className="cursor-help shrink-0"
                                                                                >
                                                                                    Suggested
                                                                                </LemonTag>
                                                                            </Tooltip>
                                                                        )}
                                                                    </div>
                                                                    {showRows && (
                                                                        <span className="text-sm text-muted-alt text-right">
                                                                            {schema.rows != null ? (
                                                                                schema.rows
                                                                            ) : (
                                                                                <Tooltip title="Row count was skipped for this table because counting would require a full scan (e.g. plain views, Memory/Buffer/Log-engine tables, or Kafka/URL table functions). The table can still be synced — we just don't know its size up front.">
                                                                                    <span className="cursor-help">
                                                                                        Skipped
                                                                                    </span>
                                                                                </Tooltip>
                                                                            )}
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            )
                                                        })}
                                                    </div>
                                                </div>
                                            ),
                                        }
                                    })}
                                />
                            </div>
                        ) : (
                            <div className="border rounded px-4 py-8 text-center text-muted-alt">No tables found</div>
                        )
                    ) : groupedDatabaseSchema.length > 1 ? (
                        <div className="border rounded bg-bg-light">
                            <LemonCollapse
                                multiple
                                embedded
                                activeKeys={expandedSchemaGroupKeys}
                                onChange={setExpandedSchemaGroupKeys}
                                panels={groupedDatabaseSchema.map(
                                    ({
                                        schemaName,
                                        tables,
                                    }: {
                                        schemaName: string
                                        tables: ExternalDataSourceSyncSchema[]
                                    }) => ({
                                        key: schemaName,
                                        header: (
                                            <div className="flex items-center justify-between gap-3 w-full">
                                                <div className="flex items-center gap-2 min-w-0">
                                                    <LemonCheckbox
                                                        checked={getSchemaSelectionState(tables)}
                                                        stopPropagation
                                                        onChange={(checked) => toggleSchemaGroup(schemaName, checked)}
                                                    />
                                                    <span className="font-semibold truncate">{schemaName}</span>
                                                </div>
                                                <span className="text-xs text-muted-alt whitespace-nowrap">
                                                    {tables.filter((t) => t.should_sync).length} of {tables.length}{' '}
                                                    tables
                                                </span>
                                            </div>
                                        ),
                                        content: (
                                            <LemonTable
                                                embedded
                                                showHeader={false}
                                                dataSource={tables}
                                                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                                                columns={warehouseColumns}
                                            />
                                        ),
                                    })
                                )}
                            />
                        </div>
                    ) : (
                        <LemonTable
                            emptyState={schemaNameFilter ? `No tables match "${schemaNameFilter}"` : 'No schemas found'}
                            dataSource={filteredDatabaseSchema}
                            pagination={{ pageSize: 100, hideOnSinglePage: true }}
                            columns={[
                                {
                                    ...warehouseColumns[0],
                                    title: (
                                        <LemonCheckbox
                                            checked={tablesAllToggledOn}
                                            onChange={(checked) =>
                                                toggleAllTables(
                                                    checked,
                                                    schemaNameFilter
                                                        ? filteredDatabaseSchema.map(
                                                              (s: ExternalDataSourceSyncSchema) => s.table
                                                          )
                                                        : undefined
                                                )
                                            }
                                        />
                                    ),
                                },
                                ...warehouseColumns.slice(1),
                            ]}
                        />
                    )}
                </div>
            </div>
            <SyncMethodModal />
            <LemonModal
                title={
                    columnSelectionSchema ? (
                        <>
                            Columns and row filters for <span className="font-mono">{columnSelectionSchema.table}</span>
                        </>
                    ) : null
                }
                description="Choose which columns to sync and add row filters to sync only matching rows. Primary-key and incremental columns are always synced."
                isOpen={columnSelectionSchema !== null}
                onClose={() => setColumnSelectionSchema(null)}
                footer={
                    <LemonButton type="primary" onClick={() => setColumnSelectionSchema(null)}>
                        Done
                    </LemonButton>
                }
            >
                <div className="min-w-[420px] flex flex-col gap-6">
                    <div className="flex flex-col gap-2">
                        <h4 className="font-semibold mb-0">Columns to sync</h4>
                        <ColumnSelectionPicker
                            hideActions
                            schema={
                                columnSelectionSchema
                                    ? {
                                          id: columnSelectionSchema.table,
                                          name: columnSelectionSchema.table,
                                          enabled_columns: columnSelectionSchema.enabled_columns,
                                          primary_key_columns: columnSelectionSchema.primary_key_columns,
                                          incremental_field: columnSelectionSchema.incremental_field,
                                          available_columns: columnSelectionSchema.available_columns.map((c) => ({
                                              name: c.field,
                                              data_type: c.type,
                                              is_nullable: c.nullable,
                                          })),
                                      }
                                    : null
                            }
                            onChange={(enabledColumns) => {
                                if (columnSelectionSchema) {
                                    setSchemaSyncedColumns(columnSelectionSchema, enabledColumns)
                                }
                            }}
                        />
                    </div>
                    {columnSelectionSchema?.sync_type !== 'cdc' && (
                        <div className="flex flex-col gap-2">
                            <h4 className="font-semibold mb-0">Row filters</h4>
                            <RowFilterEditor
                                hideActions
                                schema={
                                    columnSelectionSchema
                                        ? {
                                              id: columnSelectionSchema.table,
                                              name: columnSelectionSchema.table,
                                              row_filters: columnSelectionSchema.row_filters,
                                              available_columns: columnSelectionSchema.available_columns.map((c) => ({
                                                  name: c.field,
                                                  data_type: c.type,
                                                  is_nullable: c.nullable,
                                              })),
                                          }
                                        : null
                                }
                                onChange={(rowFilters) => {
                                    if (columnSelectionSchema) {
                                        setSchemaRowFilters(columnSelectionSchema, rowFilters)
                                    }
                                }}
                            />
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

const SyncMethodModal = (): JSX.Element => {
    const { cancelSyncMethodModal, updateSchemaSyncType, toggleSchemaShouldSync } = useActions(sourceWizardLogic)
    const { syncMethodModalOpen, currentSyncMethodModalSchema } = useValues(sourceWizardLogic)

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    return (
        <LemonModal
            title={
                <>
                    Sync method for <span className="font-mono">{currentSyncMethodModalSchema.table}</span>
                </>
            }
            isOpen={syncMethodModalOpen}
            onClose={cancelSyncMethodModal}
        >
            <SyncMethodForm
                schema={currentSyncMethodModalSchema}
                onClose={cancelSyncMethodModal}
                isNewSource
                onSave={(
                    syncType,
                    incrementalField,
                    incrementalFieldType,
                    primaryKeyColumns,
                    cdcTableMode,
                    incrementalFieldLookbackSeconds
                ) => {
                    if (syncType === 'incremental' || syncType === 'append') {
                        updateSchemaSyncType(
                            currentSyncMethodModalSchema,
                            syncType,
                            incrementalField,
                            incrementalFieldType,
                            primaryKeyColumns,
                            undefined,
                            syncType === 'incremental' ? incrementalFieldLookbackSeconds : null
                        )
                    } else if (syncType === 'cdc') {
                        updateSchemaSyncType(currentSyncMethodModalSchema, syncType, null, null, null, cdcTableMode)
                    } else {
                        updateSchemaSyncType(currentSyncMethodModalSchema, syncType ?? null, null, null, null)
                    }

                    toggleSchemaShouldSync(currentSyncMethodModalSchema, true)
                    cancelSyncMethodModal()
                }}
            />
        </LemonModal>
    )
}
