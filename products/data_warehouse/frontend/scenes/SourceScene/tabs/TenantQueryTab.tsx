import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlay, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { type HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import type {
    TenantQueryResponseApi,
    TenantQueryResponseApiResultsItemItem,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { splitDirectQuerySchemaName } from './DirectQuerySchemasTab'
import { TENANT_QUERY_PLAYGROUND_ID, tenantQueryConfigLogic } from './tenantQueryConfigLogic'

interface TenantQueryTabProps {
    id: string
    source: ExternalDataSource | null
}

interface TenantQueryTableRow {
    id: string
    qualifiedName: string
    displayName: string
    queryName: string
    schemaName: string
    isQueryable: boolean
    notQueryableReason: string | null
    tenantColumnName: string | null
    hasTenantColumnOverride: boolean
    hasTenantColumn: boolean | null
    columns: TenantQueryTableColumn[]
    tenantColumnOptions: { label: string; value: string }[]
}

interface TenantQueryTableColumn {
    name: string
    type: string | null
}

type TenantQueryColumnType = 'integer' | 'string' | 'uuid'

function shouldIgnoreTableRowClick(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && !!target.closest('button,a,input,textarea,select,[role="button"]')
}

function tenantQueryColumnType(type: string | null): TenantQueryColumnType | null {
    if (type === 'integer' || type === 'string' || type === 'uuid') {
        return type
    }
    return null
}

function isTenantQueryColumnTypeCompatible(
    type: string | null,
    tenantColumnType: TenantQueryColumnType | null
): boolean {
    if (!tenantColumnType) {
        return true
    }

    const columnType = tenantQueryColumnType(type)
    if (tenantColumnType === 'uuid') {
        return columnType === 'uuid' || columnType === 'string'
    }

    return columnType === tenantColumnType
}

function inferTenantColumnType(
    schemas: ExternalDataSourceSchema[],
    tenantColumnName: string
): TenantQueryColumnType | null {
    if (!tenantColumnName) {
        return null
    }

    const types = new Set<TenantQueryColumnType>()
    for (const schema of schemas) {
        const column = (schema.table?.columns ?? []).find((schemaColumn) => schemaColumn.name === tenantColumnName)
        const columnType = tenantQueryColumnType(typeof column?.type === 'string' ? column.type : null)
        if (columnType) {
            types.add(columnType)
        }
    }

    return types.size === 1 ? Array.from(types)[0] : null
}

function tenantQueryTableRows(
    schemas: ExternalDataSourceSchema[],
    selectedTenantColumn: string,
    tenantColumnNamesByTable: Record<string, string>,
    tenantColumnType: TenantQueryColumnType | null,
    enabledTables: string[]
): TenantQueryTableRow[] {
    const enabledTableNames = new Set(enabledTables)
    const rows = schemas.map((schema) => {
        const qualifiedName = schema.table?.name ?? schema.name
        const { schemaName, tableName } = splitDirectQuerySchemaName(qualifiedName)
        const tenantColumnOverride = tenantColumnNamesByTable[qualifiedName] ?? null
        const configuredTenantColumnName = tenantColumnOverride ?? selectedTenantColumn
        const allColumns = (schema.table?.columns ?? [])
            .map((column) => ({
                name: column.name,
                type: typeof column.type === 'string' ? column.type : null,
            }))
            .sort((columnA, columnB) => columnA.name.localeCompare(columnB.name))
        const hasTenantColumn = configuredTenantColumnName
            ? allColumns.some((column) => column.name === configuredTenantColumnName)
            : null
        const tenantColumnName = hasTenantColumn ? configuredTenantColumnName : null
        const enabledForTenantQuery =
            schema.should_sync || enabledTableNames.has(qualifiedName) || enabledTableNames.has(tableName)
        const notQueryableReason = !enabledForTenantQuery
            ? 'Disabled in Schemas'
            : configuredTenantColumnName && hasTenantColumn === false
              ? 'Missing tenant column'
              : null
        const columns = allColumns.filter((column) => column.name !== tenantColumnName)
        const tenantColumnOptions = allColumns
            .filter((column) => isTenantQueryColumnTypeCompatible(column.type, tenantColumnType))
            .map((column) => ({ label: column.name, value: column.name }))

        return {
            id: schema.id,
            qualifiedName,
            schemaName,
            displayName: tableName,
            queryName: qualifiedName,
            isQueryable: notQueryableReason === null,
            notQueryableReason,
            tenantColumnName,
            hasTenantColumnOverride: tenantColumnOverride !== null,
            hasTenantColumn,
            columns,
            tenantColumnOptions,
        }
    })

    const queryableRows = rows.filter((row) => row.isQueryable)
    const useUnqualifiedQueryNames = new Set(queryableRows.map((row) => row.schemaName)).size === 1

    return rows
        .map((row) => ({
            ...row,
            queryName: useUnqualifiedQueryNames ? row.displayName : row.qualifiedName,
        }))
        .sort((rowA, rowB) => rowA.qualifiedName.localeCompare(rowB.qualifiedName))
}

function tenantQueryTableMatchesSearch(row: TenantQueryTableRow, search: string): boolean {
    const normalizedSearch = search.trim().toLowerCase()
    if (!normalizedSearch) {
        return true
    }

    return [row.displayName, row.qualifiedName, row.queryName, row.schemaName].some((value) =>
        value.toLowerCase().includes(normalizedSearch)
    )
}

function tenantColumnTypeLabel(tenantColumnType: unknown): string | null {
    return typeof tenantColumnType === 'string' ? tenantColumnType : null
}

function configuredTenantColumnType(tenantColumnType: unknown): TenantQueryColumnType | null {
    return typeof tenantColumnType === 'string' ? tenantQueryColumnType(tenantColumnType) : null
}

function formatResultCell(value: TenantQueryResponseApiResultsItemItem): string {
    if (value === null) {
        return 'NULL'
    }

    if (typeof value === 'object') {
        return JSON.stringify(value)
    }

    return String(value)
}

function QueryTransformBlock({ title, value }: { title: string; value?: string | null }): JSX.Element | null {
    if (!value) {
        return null
    }

    return (
        <div className="space-y-1">
            <div className="text-sm font-semibold">{title}</div>
            <pre className="bg-bg-light border rounded p-3 overflow-auto text-xs whitespace-pre-wrap">{value}</pre>
        </div>
    )
}

function TenantQueryResultPreview({ response }: { response: TenantQueryResponseApi }): JSX.Element | null {
    const columns = response.columns ?? []
    const results = response.results ?? []

    if (columns.length === 0) {
        return null
    }

    return (
        <div className="space-y-1">
            <div className="text-sm font-semibold">Results</div>
            {results.length === 0 ? (
                <div className="border rounded px-4 py-3 text-sm text-muted">No rows returned</div>
            ) : (
                <div className="overflow-auto border rounded">
                    <table className="w-full text-xs">
                        <thead className="bg-bg-light border-b">
                            <tr>
                                {columns.map((column) => (
                                    <th key={column} className="text-left font-semibold px-3 py-2 whitespace-nowrap">
                                        {column}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {results.slice(0, 50).map((row, rowIndex) => (
                                <tr key={rowIndex} className="border-b last:border-b-0">
                                    {columns.map((column, columnIndex) => (
                                        <td key={column} className="px-3 py-2 align-top whitespace-nowrap">
                                            {formatResultCell(row[columnIndex] ?? null)}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

function TenantQueryPlaygroundOutput({
    error,
    isLoading,
    response,
}: {
    error: string | null
    isLoading: boolean
    response: TenantQueryResponseApi | null
}): JSX.Element {
    if (error) {
        return <LemonBanner type="error">{error}</LemonBanner>
    }

    if (response) {
        return (
            <div className="space-y-4">
                <QueryTransformBlock title="Prepared HogQL" value={response.hogql} />
                <QueryTransformBlock title="Postgres SQL" value={response.postgres_sql} />
                <TenantQueryResultPreview response={response} />
            </div>
        )
    }

    return (
        <div className="min-h-64 rounded border bg-bg-light flex items-center justify-center text-sm text-muted">
            {isLoading ? 'Running query...' : 'Results will appear here'}
        </div>
    )
}

function TenantQueryTableColumns({ columns }: { columns: TenantQueryTableColumn[] }): JSX.Element {
    if (columns.length === 0) {
        return <div className="py-2 text-sm text-muted">No queryable columns available</div>
    }

    return (
        <div className="py-2 space-y-2">
            <div className="text-sm font-semibold">Available columns</div>
            <div className="flex flex-wrap gap-2">
                {columns.map((column) => (
                    <LemonTag key={column.name} type="default" size="small">
                        <span>{column.name}</span>
                        {column.type && <span className="text-muted ml-1">{column.type}</span>}
                    </LemonTag>
                ))}
            </div>
        </div>
    )
}

function tenantQueryPlaygroundSourceQuery(query: string, connectionId: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query,
        connectionId,
    }
}

export function TenantQueryTab({ id, source }: TenantQueryTabProps): JSX.Element {
    const connectionId = source?.id || id
    const logic = tenantQueryConfigLogic({ id: connectionId })
    const {
        tenantQueryConfig,
        tenantQueryConfigError,
        tenantQueryConfigWarning,
        tenantQueryConfigLoading,
        tenantQueryConfigForm,
        tenantQueryConfigFormChanged,
        isTenantQueryConfigFormSubmitting,
        expandedTenantQueryTableIds,
        tenantQueryTableVisibility,
        tenantQueryTableSearch,
        editingTenantQueryTableColumnId,
        tenantQueryTableColumnDrafts,
        savingTenantQueryTableColumnOverride,
        tenantQueryPlaygroundResponse,
        tenantQueryPlaygroundError,
        isTenantQueryPlaygroundSubmitting,
    } = useValues(logic)
    const {
        selectTenantQueryTableInPlayground,
        setTenantQueryTableExpanded,
        toggleTenantQueryTableExpanded,
        setTenantQueryTableVisibility,
        setTenantQueryTableSearch,
        startEditingTenantQueryTableColumn,
        setTenantQueryTableColumnDraft,
        cancelEditingTenantQueryTableColumn,
        saveTenantQueryTableColumnOverride,
        submitTenantQueryPlayground,
    } = useActions(logic)

    if (tenantQueryConfigLoading || !source) {
        return <LemonSkeleton className="h-48" />
    }

    const selectedTenantColumn = tenantQueryConfigForm.tenant_column_name.trim()
    const savedTenantColumn = tenantQueryConfig?.tenant_column_name ?? ''
    const savedTenantColumnType = configuredTenantColumnType(tenantQueryConfig?.tenant_column_type)
    const inferredTenantColumnType = inferTenantColumnType(source.schemas, selectedTenantColumn)
    const selectedTenantColumnType =
        savedTenantColumn === selectedTenantColumn
            ? (savedTenantColumnType ?? inferredTenantColumnType)
            : (inferredTenantColumnType ?? savedTenantColumnType)
    const tableRows = tenantQueryTableRows(
        source.schemas,
        selectedTenantColumn,
        tenantQueryConfigForm.tenant_column_names_by_table,
        selectedTenantColumnType,
        tenantQueryConfig?.enabled_tables ?? []
    )
    const queryableTableRows = tableRows.filter((row) => row.isQueryable)
    const nonQueryableTableRows = tableRows.filter((row) => !row.isQueryable)
    const visibleTableRows = tableRows.filter(
        (row) =>
            (row.isQueryable ? tenantQueryTableVisibility.queryable : tenantQueryTableVisibility.non_queryable) &&
            tenantQueryTableMatchesSearch(row, tenantQueryTableSearch)
    )
    const configuredTenantColumnTypeLabel = tenantColumnTypeLabel(tenantQueryConfig?.tenant_column_type)
    const hasQueryableTables = queryableTableRows.length > 0
    const tenantColumnEditDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ExternalDataSource,
        AccessControlLevel.Admin,
        source.user_access_level
    )

    return (
        <div className="space-y-6 w-full">
            {!hasQueryableTables && (
                <LemonBanner type="warning">
                    Enable at least one table in the Schemas tab before turning this on.
                </LemonBanner>
            )}
            {tenantQueryConfigWarning && <LemonBanner type="warning">{tenantQueryConfigWarning}</LemonBanner>}
            {tenantQueryConfigError && <LemonBanner type="error">{tenantQueryConfigError}</LemonBanner>}
            <LemonBanner type="info">
                <div className="space-y-2">
                    <div>
                        Multi-tenancy exposes this direct Postgres connection through read-only HogQL and automatically
                        adds the tenant column filter to every queryable table. Tables without a configured tenant
                        column are disabled, and each table's tenant column is hidden from schema exports and query
                        results.
                    </div>
                    <div>
                        Query it with <code>POST /api/environments/:project_id/tenant_query/</code>. Send{' '}
                        <code>connection_id</code>, <code>query</code>, and the tenancy key as <code>tenant_value</code>{' '}
                        in the JSON body. This works well as an MCP read path: your backend or MCP tool can forward the
                        end-customer's tenant value and let PostHog enforce table scoping, schema hiding, limits, and
                        query logging.
                    </div>
                </div>
            </LemonBanner>

            <Form
                logic={tenantQueryConfigLogic}
                props={{ id: connectionId }}
                formKey="tenantQueryConfigForm"
                enableFormOnSubmit
                className="space-y-4"
            >
                <LemonField name="enabled">
                    {({ value, onChange }) => (
                        <LemonSwitch
                            checked={!!value}
                            onChange={onChange}
                            label="Enable multi-tenancy"
                            disabledReason={
                                !hasQueryableTables && !value ? 'Enable at least one table first' : undefined
                            }
                        />
                    )}
                </LemonField>

                <LemonField
                    name="tenant_column_name"
                    label="Tenant column"
                    help="Default tenant column. Click a table's tenant column below to override it for that table with a column of the same type."
                >
                    {({ value, onChange }) => (
                        <LemonInput
                            value={value}
                            onChange={onChange}
                            allowClear
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault()
                                }
                            }}
                            placeholder="customer_id"
                            disabledReason={!hasQueryableTables ? 'Enable at least one table first' : undefined}
                        />
                    )}
                </LemonField>

                <div className="grid gap-4 md:grid-cols-3">
                    <LemonField name="default_timeout_ms" label="Default timeout (ms)">
                        <LemonInput type="number" min={1} />
                    </LemonField>
                    <LemonField name="max_timeout_ms" label="Max timeout (ms)">
                        <LemonInput type="number" min={1} />
                    </LemonField>
                    <LemonField name="max_result_limit" label="Max result limit">
                        <LemonInput type="number" min={1} />
                    </LemonField>
                </div>

                <div className="flex items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
                        <span>{queryableTableRows.length} queryable tables</span>
                        {configuredTenantColumnTypeLabel && (
                            <LemonTag type="default" size="small">
                                {configuredTenantColumnTypeLabel}
                            </LemonTag>
                        )}
                    </div>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExternalDataSource}
                        minAccessLevel={AccessControlLevel.Admin}
                        userAccessLevel={source.user_access_level}
                    >
                        <LemonButton
                            type="primary"
                            center
                            htmlType="submit"
                            data-attr="tenant-query-config-save"
                            loading={isTenantQueryConfigFormSubmitting}
                            disabledReason={!tenantQueryConfigFormChanged ? 'No changes' : undefined}
                        >
                            Save
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </Form>

            {tableRows.length > 0 && (
                <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="text-base font-semibold m-0">Tables</h3>
                        <div className="flex flex-wrap items-center gap-3">
                            <LemonCheckbox
                                checked={tenantQueryTableVisibility.queryable}
                                onChange={(checked) => setTenantQueryTableVisibility('queryable', checked)}
                                label={`Queryable (${queryableTableRows.length})`}
                            />
                            <LemonCheckbox
                                checked={tenantQueryTableVisibility.non_queryable}
                                onChange={(checked) => setTenantQueryTableVisibility('non_queryable', checked)}
                                label={`Non-queryable (${nonQueryableTableRows.length})`}
                            />
                        </div>
                    </div>
                    <LemonInput
                        value={tenantQueryTableSearch}
                        onChange={setTenantQueryTableSearch}
                        allowClear
                        placeholder="Search tables"
                        className="max-w-md"
                    />
                    <LemonTable
                        dataSource={visibleTableRows}
                        rowKey="id"
                        emptyState="No tables match these filters"
                        onRow={(row) => ({
                            onClick: (event) => {
                                if (shouldIgnoreTableRowClick(event.target)) {
                                    return
                                }
                                toggleTenantQueryTableExpanded(row.id)
                            },
                        })}
                        expandable={{
                            isRowExpanded: (row) => expandedTenantQueryTableIds.includes(row.id),
                            onRowExpand: (row) => setTenantQueryTableExpanded(row.id, true),
                            onRowCollapse: (row) => setTenantQueryTableExpanded(row.id, false),
                            expandedRowRender: function RenderTenantQueryTableColumns(row) {
                                return <TenantQueryTableColumns columns={row.columns} />
                            },
                        }}
                        columns={[
                            {
                                key: 'tableName',
                                title: 'Table',
                                render: function RenderTableName(_, row) {
                                    return <span>{row.displayName}</span>
                                },
                            },
                            {
                                key: 'status',
                                title: 'Status',
                                render: function RenderTableStatus(_, row) {
                                    return row.isQueryable ? (
                                        <LemonTag type="success" size="small">
                                            Queryable
                                        </LemonTag>
                                    ) : (
                                        <LemonTag
                                            type={
                                                row.notQueryableReason === 'Missing tenant column'
                                                    ? 'danger'
                                                    : 'default'
                                            }
                                            size="small"
                                        >
                                            {row.notQueryableReason ?? 'Not queryable'}
                                        </LemonTag>
                                    )
                                },
                            },
                            {
                                key: 'tenantColumn',
                                title: 'Tenant column',
                                render: function RenderTenantColumn(_, row) {
                                    if (!selectedTenantColumn) {
                                        return <span className="text-muted">Not selected</span>
                                    }

                                    if (editingTenantQueryTableColumnId === row.id) {
                                        const draftTenantColumn =
                                            tenantQueryTableColumnDrafts[row.id] ?? row.tenantColumnName ?? ''

                                        return (
                                            <div
                                                className="flex items-center gap-2 min-w-64"
                                                onClick={(event) => event.stopPropagation()}
                                                onBlur={(event) => {
                                                    const nextFocusedElement = event.relatedTarget
                                                    if (
                                                        nextFocusedElement instanceof Node &&
                                                        event.currentTarget.contains(nextFocusedElement)
                                                    ) {
                                                        return
                                                    }

                                                    window.setTimeout(cancelEditingTenantQueryTableColumn, 150)
                                                }}
                                            >
                                                <LemonSelect<string>
                                                    value={draftTenantColumn || undefined}
                                                    onSelect={(value) => {
                                                        const nextTenantColumn = value ?? ''
                                                        setTenantQueryTableColumnDraft(row.id, nextTenantColumn)
                                                        if (nextTenantColumn) {
                                                            saveTenantQueryTableColumnOverride(
                                                                row.id,
                                                                row.qualifiedName,
                                                                nextTenantColumn
                                                            )
                                                        }
                                                    }}
                                                    options={row.tenantColumnOptions}
                                                    placeholder="Select tenant column"
                                                    fullWidth
                                                    loading={savingTenantQueryTableColumnOverride === row.id}
                                                    disabledReason={
                                                        tenantColumnEditDisabledReason ||
                                                        (row.tenantColumnOptions.length === 0
                                                            ? 'No columns match the global tenant type'
                                                            : undefined)
                                                    }
                                                />
                                                <LemonButton
                                                    size="small"
                                                    type="tertiary"
                                                    icon={<IconX />}
                                                    onClick={(event) => {
                                                        event.stopPropagation()
                                                        cancelEditingTenantQueryTableColumn()
                                                    }}
                                                />
                                            </div>
                                        )
                                    }

                                    const tenantColumnTag = row.hasTenantColumn ? (
                                        <LemonTag
                                            type={row.hasTenantColumnOverride ? 'warning' : 'success'}
                                            size="small"
                                        >
                                            {row.tenantColumnName}
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="danger" size="small">
                                            Missing
                                        </LemonTag>
                                    )

                                    return (
                                        <span
                                            role="button"
                                            tabIndex={0}
                                            className="inline-flex cursor-pointer"
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                startEditingTenantQueryTableColumn(row.id, row.tenantColumnName ?? '')
                                            }}
                                            onKeyDown={(event) => {
                                                if (event.key === 'Enter' || event.key === ' ') {
                                                    event.preventDefault()
                                                    event.stopPropagation()
                                                    startEditingTenantQueryTableColumn(
                                                        row.id,
                                                        row.tenantColumnName ?? ''
                                                    )
                                                }
                                            }}
                                        >
                                            {tenantColumnTag}
                                        </span>
                                    )
                                },
                            },
                            {
                                key: 'playground',
                                title: '',
                                align: 'right',
                                render: function RenderPlaygroundQueryButton(_, row) {
                                    return (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            icon={<IconPlay />}
                                            disabledReason={
                                                !row.isQueryable
                                                    ? (row.notQueryableReason ?? 'Not queryable')
                                                    : tenantQueryConfigFormChanged
                                                      ? 'Save configuration changes first'
                                                      : !tenantQueryConfig?.enabled
                                                        ? 'Enable multi-tenancy first'
                                                        : undefined
                                            }
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                selectTenantQueryTableInPlayground(row.queryName)
                                            }}
                                        >
                                            Query
                                        </LemonButton>
                                    )
                                },
                            },
                        ]}
                        pagination={{ pageSize: 50, hideOnSinglePage: true }}
                    />
                </div>
            )}

            <div id={TENANT_QUERY_PLAYGROUND_ID} className="border-t pt-6 space-y-4">
                <div className="flex items-center justify-between gap-3">
                    <h3 className="text-base font-semibold m-0">Playground</h3>
                    {tenantQueryConfig?.enabled ? (
                        <LemonTag type="success" size="small">
                            Enabled
                        </LemonTag>
                    ) : (
                        <LemonTag type="default" size="small">
                            Disabled
                        </LemonTag>
                    )}
                </div>

                <Form
                    logic={tenantQueryConfigLogic}
                    props={{ id: connectionId }}
                    formKey="tenantQueryPlayground"
                    enableFormOnSubmit
                    className="space-y-4"
                >
                    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_180px]">
                        <LemonField name="tenant_value" label="Tenant value">
                            <LemonInput placeholder="42" />
                        </LemonField>
                        <LemonField name="timeout_ms" label="Timeout (ms)">
                            <LemonInput type="number" min={1} placeholder="Default" />
                        </LemonField>
                    </div>

                    <LemonField name="query" label="Query">
                        {({ value, onChange }) => {
                            const query = typeof value === 'string' ? value : ''

                            return (
                                <div className="space-y-1">
                                    <CodeEditorInline
                                        queryKey={`tenant-query-playground/${connectionId}`}
                                        value={query}
                                        onChange={(newValue) => onChange(newValue ?? '')}
                                        language="hogQL"
                                        sourceQuery={tenantQueryPlaygroundSourceQuery(query, connectionId)}
                                        minHeight="180px"
                                        maxHeight="60vh"
                                        onPressCmdEnter={() => submitTenantQueryPlayground()}
                                    />
                                    <div className="text-xs text-muted">
                                        You can query{' '}
                                        <Link
                                            onClick={() => selectTenantQueryTableInPlayground('system.tables')}
                                            data-attr="tenant-query-system-tables"
                                        >
                                            system.tables
                                        </Link>{' '}
                                        and{' '}
                                        <Link
                                            onClick={() => selectTenantQueryTableInPlayground('system.fields')}
                                            data-attr="tenant-query-system-fields"
                                        >
                                            system.fields
                                        </Link>{' '}
                                        for introspection
                                    </div>
                                </div>
                            )
                        }}
                    </LemonField>

                    <div className="flex justify-start">
                        <LemonButton
                            type="secondary"
                            center
                            htmlType="submit"
                            data-attr="tenant-query-playground-run"
                            loading={isTenantQueryPlaygroundSubmitting}
                            disabledReason={
                                tenantQueryConfigFormChanged
                                    ? 'Save configuration changes first'
                                    : !tenantQueryConfig?.enabled
                                      ? 'Enable multi-tenancy first'
                                      : undefined
                            }
                        >
                            Run query
                        </LemonButton>
                    </div>

                    <TenantQueryPlaygroundOutput
                        error={tenantQueryPlaygroundError}
                        isLoading={isTenantQueryPlaygroundSubmitting}
                        response={tenantQueryPlaygroundResponse}
                    />
                </Form>
            </div>
        </div>
    )
}
