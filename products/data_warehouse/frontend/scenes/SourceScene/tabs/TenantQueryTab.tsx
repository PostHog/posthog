import { useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import type { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'

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
    tableName: string
    hasTenantColumn: boolean | null
}

interface TenantColumnOption {
    label: string
    value: string
}

function tenantColumnOptionsFromSchemas(schemas: ExternalDataSourceSchema[]): TenantColumnOption[] {
    const enabledSchemas = schemas.filter((schema) => schema.should_sync)
    if (enabledSchemas.length === 0 || enabledSchemas.some((schema) => !schema.table?.columns?.length)) {
        return []
    }

    const columnSets = enabledSchemas
        .map((schema) => schema.table?.columns?.map((column) => column.name) ?? [])
        .map((columns) => new Set(columns))

    if (columnSets.length === 0) {
        return selectedTenantColumn ? [{ label: selectedTenantColumn, value: selectedTenantColumn }] : []
    }

    const [firstColumnSet, ...otherColumnSets] = columnSets
    const commonColumns = Array.from(firstColumnSet)
        .filter((column) => otherColumnSets.every((columnSet) => columnSet.has(column)))
        .sort((columnA, columnB) => columnA.localeCompare(columnB))

    return commonColumns.map((column) => ({ label: column, value: column }))
}

function tenantQueryTableRows(
    schemas: ExternalDataSourceSchema[],
    selectedTenantColumn: string
): TenantQueryTableRow[] {
    return schemas
        .filter((schema) => schema.should_sync)
        .map((schema) => {
            const qualifiedName = schema.table?.name ?? schema.name
            const hasTenantColumn = selectedTenantColumn
                ? (schema.table?.columns ?? []).some((column) => column.name === selectedTenantColumn)
                : null

            return {
                id: schema.id,
                tableName: qualifiedName,
                hasTenantColumn,
            }
        })
        .sort((rowA, rowB) => rowA.tableName.localeCompare(rowB.tableName))
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

export function TenantQueryTab({ id, source }: TenantQueryTabProps): JSX.Element {
    const logic = tenantQueryConfigLogic({ id })
    const {
        tenantQueryConfig,
        tenantQueryConfigLoading,
        tenantQueryConfigForm,
        tenantQueryConfigFormChanged,
        isTenantQueryConfigFormSubmitting,
        tenantQueryPlaygroundResponse,
        tenantQueryPlaygroundError,
        isTenantQueryPlaygroundSubmitting,
    } = useValues(logic)

    if (tenantQueryConfigLoading || !source) {
        return <LemonSkeleton className="h-48" />
    }

    const selectedTenantColumn = tenantQueryConfigForm.tenant_column_name.trim()
    const tenantColumnOptions = tenantColumnOptionsFromSchemas(source.schemas)
    const tenantColumnOptionValues = new Set(tenantColumnOptions.map((option) => option.value))
    const shouldUseTenantColumnSelect =
        tenantColumnOptions.length > 0 && (!selectedTenantColumn || tenantColumnOptionValues.has(selectedTenantColumn))
    const enabledTables = tenantQueryTableRows(source.schemas, selectedTenantColumn)
    const configuredTenantColumnType = tenantColumnTypeLabel(tenantQueryConfig?.tenant_column_type)
    const hasQueryableTables = enabledTables.length > 0

    return (
        <div className="space-y-6 max-w-4xl">
            {!hasQueryableTables && (
                <LemonBanner type="warning">
                    Enable at least one table in the Schemas tab before turning this on.
                </LemonBanner>
            )}

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
                            disabledReason={!hasQueryableTables ? 'Enable at least one table first' : undefined}
                        />
                    )}
                </LemonField>

                <LemonField
                    name="tenant_column_name"
                    label="Tenant column"
                    help="The column must exist on every queryable table. It is hidden from schema exports and query results."
                >
                    {({ value, onChange }) =>
                        shouldUseTenantColumnSelect ? (
                            <LemonSelect
                                value={value || undefined}
                                onChange={(nextValue) => onChange(nextValue ?? '')}
                                options={tenantColumnOptions as LemonSelectOptions<string>}
                                placeholder="Select tenant column"
                                fullWidth
                            />
                        ) : (
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
                        )
                    }
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
                        <span>{enabledTables.length} queryable tables</span>
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

            {enabledTables.length > 0 && (
                <LemonTable
                    dataSource={enabledTables}
                    columns={[
                        {
                            key: 'tableName',
                            title: 'Queryable table',
                            render: function RenderTableName(_, row) {
                                const { tableName } = splitDirectQuerySchemaName(row.tableName)
                                return <span>{tableName}</span>
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
                    ]}
                    pagination={{ pageSize: 50, hideOnSinglePage: true }}
                />
            )}
        </div>
    )
}
