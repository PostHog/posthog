import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlay } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import type {
    TenantQueryResponseApi,
    TenantQueryResponseApiResultsItemItem,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { splitDirectQuerySchemaName } from './DirectQuerySchemasTab'
import { tenantQueryConfigLogic } from './tenantQueryConfigLogic'

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
    hasTenantColumn: boolean | null
    columns: TenantQueryTableColumn[]
}

interface TenantQueryTableColumn {
    name: string
    type: string | null
}

function shouldIgnoreTableRowClick(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && !!target.closest('button,a,input,textarea,select,[role="button"]')
}

function tenantQueryTableRows(
    schemas: ExternalDataSourceSchema[],
    selectedTenantColumn: string
): TenantQueryTableRow[] {
    const rows = schemas.map((schema) => {
        const qualifiedName = schema.table?.name ?? schema.name
        const { schemaName, tableName } = splitDirectQuerySchemaName(qualifiedName)
        const hasTenantColumn = selectedTenantColumn
            ? (schema.table?.columns ?? []).some((column) => column.name === selectedTenantColumn)
            : null
        const notQueryableReason = !schema.should_sync
            ? 'Disabled in Schemas'
            : selectedTenantColumn && hasTenantColumn === false
              ? 'Missing tenant column'
              : null
        const columns = (schema.table?.columns ?? [])
            .filter((column) => column.name !== selectedTenantColumn)
            .map((column) => ({
                name: column.name,
                type: typeof column.type === 'string' ? column.type : null,
            }))
            .sort((columnA, columnB) => columnA.name.localeCompare(columnB.name))

        return {
            id: schema.id,
            qualifiedName,
            schemaName,
            displayName: tableName,
            queryName: qualifiedName,
            isQueryable: notQueryableReason === null,
            notQueryableReason,
            hasTenantColumn,
            columns,
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

function tenantColumnTypeLabel(tenantColumnType: unknown): string | null {
    return typeof tenantColumnType === 'string' ? tenantColumnType : null
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

export function TenantQueryTab({ id, source }: TenantQueryTabProps): JSX.Element {
    const logic = tenantQueryConfigLogic({ id })
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
        tenantQueryPlaygroundResponse,
        tenantQueryPlaygroundError,
        isTenantQueryPlaygroundSubmitting,
    } = useValues(logic)
    const {
        selectTenantQueryTableInPlayground,
        setTenantQueryTableExpanded,
        toggleTenantQueryTableExpanded,
        setTenantQueryTableVisibility,
    } = useActions(logic)

    if (tenantQueryConfigLoading || !source) {
        return <LemonSkeleton className="h-48" />
    }

    const selectedTenantColumn = tenantQueryConfigForm.tenant_column_name.trim()
    const tableRows = tenantQueryTableRows(source.schemas, selectedTenantColumn)
    const queryableTableRows = tableRows.filter((row) => row.isQueryable)
    const nonQueryableTableRows = tableRows.filter((row) => !row.isQueryable)
    const visibleTableRows = tableRows.filter((row) =>
        row.isQueryable ? tenantQueryTableVisibility.queryable : tenantQueryTableVisibility.non_queryable
    )
    const configuredTenantColumnType = tenantColumnTypeLabel(tenantQueryConfig?.tenant_column_type)
    const hasQueryableTables = queryableTableRows.length > 0

    return (
        <div className="space-y-6 max-w-4xl">
            {!hasQueryableTables && (
                <LemonBanner type="warning">
                    Enable at least one table in the Schemas tab before turning this on.
                </LemonBanner>
            )}
            {tenantQueryConfigWarning && <LemonBanner type="warning">{tenantQueryConfigWarning}</LemonBanner>}
            {tenantQueryConfigError && <LemonBanner type="error">{tenantQueryConfigError}</LemonBanner>}
            <LemonBanner type="info">
                Multi-tenancy exposes this direct Postgres connection through read-only HogQL and automatically adds the
                tenant column filter to every queryable table. Tables without that column are disabled, and the tenant
                column is hidden from schema exports and query results.
            </LemonBanner>

            <Form
                logic={tenantQueryConfigLogic}
                props={{ id }}
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
                    help="Tables without this column are disabled. The tenant column is hidden from schema exports and query results."
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
                        {configuredTenantColumnType && (
                            <LemonTag type="default" size="small">
                                {configuredTenantColumnType}
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

                                    return row.hasTenantColumn ? (
                                        <LemonTag type="success" size="small">
                                            {selectedTenantColumn}
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="danger" size="small">
                                            Missing
                                        </LemonTag>
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
                                                    : undefined
                                            }
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                selectTenantQueryTableInPlayground(row.queryName)
                                            }}
                                        >
                                            Select *
                                        </LemonButton>
                                    )
                                },
                            },
                        ]}
                        pagination={{ pageSize: 50, hideOnSinglePage: true }}
                    />
                </div>
            )}

            <div className="border-t pt-6 space-y-4">
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
                    props={{ id }}
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
                        <LemonTextArea minRows={6} placeholder="select * from trips" />
                    </LemonField>

                    <div className="flex justify-end">
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
                </Form>

                {tenantQueryPlaygroundError && <LemonBanner type="error">{tenantQueryPlaygroundError}</LemonBanner>}

                {tenantQueryPlaygroundResponse && (
                    <div className="space-y-4">
                        <QueryTransformBlock title="Prepared HogQL" value={tenantQueryPlaygroundResponse.hogql} />
                        <QueryTransformBlock title="Postgres SQL" value={tenantQueryPlaygroundResponse.postgres_sql} />
                        <TenantQueryResultPreview response={tenantQueryPlaygroundResponse} />
                    </div>
                )}
            </div>
        </div>
    )
}
