import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconInfo, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonCollapse, LemonModal, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from 'products/data_warehouse/frontend/utils'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'
import { splitDirectQueryTableName } from './directQuerySchemaUtils'
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
        openSyncMethodModal,
        toggleAllTables,
        toggleDirectQuerySchemaGroup,
        setExpandedDirectQuerySchemaKeys,
    } = useActions(sourceWizardLogic)
    const {
        databaseSchema,
        suggestedTablesMap,
        isDirectQueryMode,
        source,
        groupedDirectQueryDatabaseSchema,
        expandedDirectQuerySchemaKeys,
        tablesAllToggledOn,
    } = useValues(sourceWizardLogic)

    const onClickCheckbox = (schema: ExternalDataSourceSyncSchema, checked: boolean): void => {
        if (!isDirectQueryMode && schema.sync_type === null) {
            openSyncMethodModal(schema)
            return
        }
        toggleSchemaShouldSync(schema, checked)
    }

    const shouldShowSyncColumns = !isDirectQueryMode

    // scroll to top of container
    useEffect(() => {
        containerRef?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
    }, [containerRef])

    const showRows = databaseSchema.some((schema) => schema.rows != null)

    return (
        <>
            <div className="flex flex-col gap-2">
                <div className="max-h-[60vh] overflow-y-auto">
                    {isDirectQueryMode ? (
                        groupedDirectQueryDatabaseSchema.length > 0 ? (
                            <div className="border rounded bg-bg-light">
                                <LemonCollapse
                                    multiple
                                    embedded
                                    activeKeys={expandedDirectQuerySchemaKeys}
                                    onChange={setExpandedDirectQuerySchemaKeys}
                                    panels={groupedDirectQueryDatabaseSchema.map(({ schemaName, tables }) => {
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
                                                                toggleDirectQuerySchemaGroup(schemaName, checked)
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
                                                            const { tableName } = splitDirectQueryTableName(
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
                                                                        onChange={(checked) =>
                                                                            onClickCheckbox(schema, checked)
                                                                        }
                                                                    />
                                                                    <div className="flex items-center gap-2 min-w-0">
                                                                        <span
                                                                            className="font-mono cursor-pointer truncate"
                                                                            onClick={() =>
                                                                                onClickCheckbox(
                                                                                    schema,
                                                                                    !schema.should_sync
                                                                                )
                                                                            }
                                                                        >
                                                                            {tableName}
                                                                        </span>
                                                                        {schema.description && (
                                                                            <Tooltip title={schema.description}>
                                                                                <IconInfo className="text-muted-alt text-base shrink-0" />
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
                                                                            {schema.rows != null
                                                                                ? schema.rows
                                                                                : 'Unknown'}
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
                    ) : (
                        <LemonTable
                            emptyState="No schemas found"
                            dataSource={databaseSchema}
                            columns={[
                                {
                                    title: (
                                        <LemonCheckbox
                                            checked={tablesAllToggledOn}
                                            onChange={(checked) => toggleAllTables(checked)}
                                        />
                                    ),
                                    width: 0,
                                    key: 'enabled',
                                    render: function RenderEnabled(_, schema) {
                                        return (
                                            <LemonCheckbox
                                                checked={schema.should_sync}
                                                onChange={(checked) => onClickCheckbox(schema, checked)}
                                            />
                                        )
                                    },
                                },
                                {
                                    title: 'Table',
                                    key: 'table',
                                    render: function RenderTable(_, schema) {
                                        const isSuggested = suggestedTablesMap[schema.table] !== undefined
                                        const tooltip =
                                            suggestedTablesMap[schema.table] ??
                                            'This table is suggested to be enabled for this source'

                                        return (
                                            <div className="flex items-center gap-2">
                                                <span
                                                    className="font-mono cursor-pointer"
                                                    onClick={() => onClickCheckbox(schema, !schema.should_sync)}
                                                >
                                                    {schema.table}
                                                </span>
                                                {schema.description && (
                                                    <Tooltip title={schema.description}>
                                                        <IconInfo className="text-muted-alt text-base" />
                                                    </Tooltip>
                                                )}
                                                {isSuggested && (
                                                    <Tooltip title={tooltip} placement="top">
                                                        <LemonTag type="primary" className="cursor-help">
                                                            Suggested
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
                                    render: function RenderRows(_, schema) {
                                        return schema.rows != null ? schema.rows : 'Unknown'
                                    },
                                },
                                {
                                    key: 'sync_field',
                                    title: 'Sync field',
                                    align: 'right',
                                    tooltip:
                                        'Incremental and append-only refresh methods key on a unique field to determine the most up-to-date data.',
                                    isHidden:
                                        !shouldShowSyncColumns || !databaseSchema.some((schema) => schema.sync_type),
                                    render: function RenderSyncType(_, schema) {
                                        if (isDirectQueryMode) {
                                            return (
                                                <span className="text-xs text-muted-foreground">
                                                    Only selected tables are queryable in direct mode
                                                </span>
                                            )
                                        }
                                        if (!schema.incremental_available && !schema.append_available) {
                                            return (
                                                <span className="text-xs text-muted-foreground">
                                                    Incremental sync not supported
                                                </span>
                                            )
                                        }

                                        if (schema.sync_type === 'webhook') {
                                            return <LemonTag type="success">Webhook</LemonTag>
                                        }

                                        if (
                                            schema.sync_type !== 'full_refresh' &&
                                            schema.sync_type !== null &&
                                            schema.incremental_field
                                        ) {
                                            const field =
                                                schema.incremental_fields.find(
                                                    (f) => f.field == schema.incremental_field
                                                ) ?? null

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

                                        return (
                                            <span className="text-xs text-muted-foreground">
                                                No sync field selected
                                            </span>
                                        )
                                    },
                                },
                                {
                                    key: 'primary_key',
                                    title: 'Primary key',
                                    align: 'right',
                                    tooltip:
                                        'The column(s) used to uniquely identify rows for deduplication during incremental syncs. Auto-detected if not set.',
                                    isHidden:
                                        !shouldShowSyncColumns ||
                                        !databaseSchema.some((schema) => schema.sync_type === 'incremental'),
                                    render: function RenderPrimaryKey(_, schema) {
                                        if (schema.sync_type !== 'incremental') {
                                            return (
                                                <span className="text-xs text-muted-foreground">
                                                    No primary key selected
                                                </span>
                                            )
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
                                    align: 'right',
                                    isHidden: !shouldShowSyncColumns,
                                    tooltip:
                                        'Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync',
                                    render: function RenderSyncType(_, schema) {
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
                                                        !schema.incremental_available && !schema.append_available
                                                            ? 'Full refresh is the only supported sync method for this table'
                                                            : undefined
                                                    }
                                                >
                                                    {SyncTypeLabelMap[schema.sync_type]}
                                                </LemonButton>
                                            </div>
                                        )
                                    },
                                },
                            ]}
                        />
                    )}
                </div>
            </div>
            <SyncMethodModal />
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
                onSave={(syncType, incrementalField, incrementalFieldType, primaryKeyColumns, cdcTableMode) => {
                    if (syncType === 'incremental' || syncType === 'append') {
                        updateSchemaSyncType(
                            currentSyncMethodModalSchema,
                            syncType,
                            incrementalField,
                            incrementalFieldType,
                            primaryKeyColumns
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
