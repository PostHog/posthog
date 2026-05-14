import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms, type DeepPartialMap, type ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    tenantQueryConfigCreate,
    tenantQueryConfigLoadCreate,
    tenantQueryCreate,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    TenantQueryConfigRequestApi,
    TenantQueryConfigResponseApi,
    TenantQueryRequestApi,
    TenantQueryResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import type { tenantQueryConfigLogicType } from './tenantQueryConfigLogicType'

export interface TenantQueryConfigLogicProps {
    id: string
}

export interface TenantQueryConfigFormValues {
    enabled: boolean
    tenant_column_name: string
    tenant_column_names_by_table: Record<string, string>
    default_timeout_ms: number | string
    max_timeout_ms: number | string
    max_result_limit: number | string
}

export interface TenantQueryPlaygroundFormValues {
    tenant_value: string
    query: string
    timeout_ms: number | string | ''
}

export interface TenantQueryTableVisibility {
    queryable: boolean
    non_queryable: boolean
}

export type TenantQueryTableVisibilityKey = keyof TenantQueryTableVisibility

export const TENANT_QUERY_PLAYGROUND_ID = 'tenant-query-playground'
export const TENANT_QUERY_TABLE_DISABLED = '__posthog_table_disabled__'
export const TENANT_QUERY_NO_TENANT_FIELD = '__posthog_no_tenant_field__'
export const TENANT_QUERY_FOREIGN_KEY_FIELD = '__posthog_foreign_key_field__'

const DEFAULT_TENANT_QUERY_CONFIG_FORM: TenantQueryConfigFormValues = {
    enabled: false,
    tenant_column_name: '',
    tenant_column_names_by_table: {},
    default_timeout_ms: 30_000,
    max_timeout_ms: 120_000,
    max_result_limit: 100_000,
}

const DEFAULT_TENANT_QUERY_PLAYGROUND_FORM: TenantQueryPlaygroundFormValues = {
    tenant_value: '1',
    query: 'select * from system.tables',
    timeout_ms: '',
}

const DEFAULT_TENANT_QUERY_TABLE_VISIBILITY: TenantQueryTableVisibility = {
    queryable: true,
    non_queryable: false,
}

function configToForm(config: TenantQueryConfigResponseApi | null): TenantQueryConfigFormValues {
    if (!config) {
        return DEFAULT_TENANT_QUERY_CONFIG_FORM
    }

    return {
        enabled: config.enabled,
        tenant_column_name: config.tenant_column_name ?? '',
        tenant_column_names_by_table: config.tenant_column_names_by_table ?? {},
        default_timeout_ms: config.default_timeout_ms,
        max_timeout_ms: config.max_timeout_ms,
        max_result_limit: config.max_result_limit,
    }
}

function defaultTenantValueForType(tenantColumnType: unknown): string {
    if (tenantColumnType === 'uuid') {
        return '00000000-0000-0000-0000-000000000001'
    }
    if (tenantColumnType === 'string') {
        return 'tenant_1'
    }
    return '1'
}

function positiveInteger(value: number | string): number | null {
    const parsedValue = typeof value === 'number' ? value : Number(value)

    if (!Number.isFinite(parsedValue) || !Number.isInteger(parsedValue) || parsedValue < 1) {
        return null
    }

    return parsedValue
}

function formToRequestPayload(
    connectionId: string | null | undefined,
    formValues: TenantQueryConfigFormValues
): TenantQueryConfigRequestApi | null {
    const trimmedConnectionId = connectionId?.trim()
    const defaultTimeoutMs = positiveInteger(formValues.default_timeout_ms)
    const maxTimeoutMs = positiveInteger(formValues.max_timeout_ms)
    const maxResultLimit = positiveInteger(formValues.max_result_limit)

    if (!trimmedConnectionId || defaultTimeoutMs === null || maxTimeoutMs === null || maxResultLimit === null) {
        return null
    }

    return {
        connection_id: trimmedConnectionId,
        enabled: formValues.enabled,
        tenant_column_name: formValues.tenant_column_name.trim() || null,
        tenant_column_names_by_table: Object.fromEntries(
            Object.entries(formValues.tenant_column_names_by_table)
                .map(([tableName, tenantColumnName]) => [tableName.trim(), tenantColumnName.trim()])
                .filter(([tableName, tenantColumnName]) => tableName && tenantColumnName)
        ),
        default_timeout_ms: defaultTimeoutMs,
        max_timeout_ms: maxTimeoutMs,
        max_result_limit: maxResultLimit,
    }
}

function playgroundFormToRequestPayload(
    connectionId: string | null | undefined,
    formValues: TenantQueryPlaygroundFormValues
): TenantQueryRequestApi | null {
    const trimmedConnectionId = connectionId?.trim()
    const timeoutMs = formValues.timeout_ms === '' ? undefined : positiveInteger(formValues.timeout_ms)
    if (!trimmedConnectionId || timeoutMs === null) {
        return null
    }

    return {
        connection_id: trimmedConnectionId,
        tenant_value: formValues.tenant_value.trim(),
        query: formValues.query,
        ...(timeoutMs !== undefined ? { timeout_ms: timeoutMs } : {}),
    }
}

function tenantQueryConfigErrorMessage(error: any): string {
    const message = error?.detail || error?.message
    return typeof message === 'string' ? message : 'Unable to save multi-tenancy configuration'
}

function disabledTablesWarning(disabledTables: string[] | undefined): string | null {
    if (!disabledTables?.length) {
        return null
    }

    const visibleTables = disabledTables.slice(0, 8).join(', ')
    const hiddenTableCount = disabledTables.length - 8
    const suffix = hiddenTableCount > 0 ? `, and ${hiddenTableCount} more` : ''

    return `Saved configuration and disabled ${disabledTables.length} table${
        disabledTables.length === 1 ? '' : 's'
    } without the tenant column: ${visibleTables}${suffix}.`
}

function escapeHogQLIdentifierPart(identifierPart: string): string {
    if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(identifierPart)) {
        return identifierPart
    }

    return `\`${identifierPart.replace(/`/g, '``')}\``
}

function selectAllQueryForTable(tableName: string): string {
    return `select * from ${tableName.split('.').map(escapeHogQLIdentifierPart).join('.')}`
}

function scrollToTenantQueryPlayground(): void {
    if (typeof document === 'undefined') {
        return
    }

    document.getElementById(TENANT_QUERY_PLAYGROUND_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export const tenantQueryConfigLogic = kea<tenantQueryConfigLogicType>([
    path(['products', 'dataWarehouse', 'tenantQueryConfigLogic']),
    props({} as TenantQueryConfigLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setTenantQueryConfigError: (error: string | null) => ({ error }),
        setTenantQueryConfigWarning: (warning: string | null) => ({ warning }),
        setTenantQueryPlaygroundResponse: (response: TenantQueryResponseApi | null) => ({ response }),
        setTenantQueryPlaygroundError: (error: string | null) => ({ error }),
        selectTenantQueryTableInPlayground: (tableName: string) => ({ tableName }),
        setTenantQueryTableExpanded: (tableId: string, expanded: boolean) => ({ tableId, expanded }),
        toggleTenantQueryTableExpanded: (tableId: string) => ({ tableId }),
        setTenantQueryTableVisibility: (visibility: TenantQueryTableVisibilityKey, visible: boolean) => ({
            visibility,
            visible,
        }),
        setTenantQueryTableSearch: (search: string) => ({ search }),
        saveTenantQueryTableColumnOverride: (tableId: string, tableName: string, tenantColumnName: string) => ({
            tableId,
            tableName,
            tenantColumnName,
        }),
        setSavingTenantQueryTableColumnOverride: (tableId: string | null) => ({ tableId }),
    }),
    loaders(({ props, values }) => ({
        tenantQueryConfig: [
            null as TenantQueryConfigResponseApi | null,
            {
                loadTenantQueryConfig: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }

                    return await tenantQueryConfigLoadCreate(String(values.currentTeamId), {
                        connection_id: props.id,
                    })
                },
            },
        ],
    })),
    reducers({
        tenantQueryConfigError: [
            null as string | null,
            {
                setTenantQueryConfigError: (_, { error }) => error,
                submitTenantQueryConfigRequest: () => null,
                loadTenantQueryConfigSuccess: () => null,
            },
        ],
        tenantQueryConfigWarning: [
            null as string | null,
            {
                setTenantQueryConfigWarning: (_, { warning }) => warning,
                submitTenantQueryConfigRequest: () => null,
                loadTenantQueryConfigSuccess: () => null,
            },
        ],
        tenantQueryPlaygroundResponse: [
            null as TenantQueryResponseApi | null,
            {
                setTenantQueryPlaygroundResponse: (_, { response }) => response,
                submitTenantQueryPlaygroundRequest: () => null,
            },
        ],
        tenantQueryPlaygroundError: [
            null as string | null,
            {
                setTenantQueryPlaygroundError: (_, { error }) => error,
                submitTenantQueryPlaygroundRequest: () => null,
            },
        ],
        expandedTenantQueryTableIds: [
            [] as string[],
            {
                setTenantQueryTableExpanded: (state, { tableId, expanded }) =>
                    expanded
                        ? Array.from(new Set([...state, tableId]))
                        : state.filter((expandedTableId) => expandedTableId !== tableId),
                toggleTenantQueryTableExpanded: (state, { tableId }) =>
                    state.includes(tableId)
                        ? state.filter((expandedTableId) => expandedTableId !== tableId)
                        : [...state, tableId],
            },
        ],
        tenantQueryTableVisibility: [
            DEFAULT_TENANT_QUERY_TABLE_VISIBILITY,
            {
                setTenantQueryTableVisibility: (state, { visibility, visible }) => ({
                    ...state,
                    [visibility]: visible,
                }),
            },
        ],
        tenantQueryTableSearch: [
            '',
            {
                setTenantQueryTableSearch: (_, { search }) => search,
            },
        ],
        savingTenantQueryTableColumnOverride: [
            null as string | null,
            {
                setSavingTenantQueryTableColumnOverride: (_, { tableId }) => tableId,
            },
        ],
    }),
    forms(({ props, values, actions }) => ({
        tenantQueryConfigForm: {
            defaults: DEFAULT_TENANT_QUERY_CONFIG_FORM,
            errors: (formValues: TenantQueryConfigFormValues) => {
                const errors: DeepPartialMap<TenantQueryConfigFormValues, ValidationErrorType> = {}
                const tenantColumnName = formValues.tenant_column_name.trim()
                const defaultTimeoutMs = positiveInteger(formValues.default_timeout_ms)
                const maxTimeoutMs = positiveInteger(formValues.max_timeout_ms)
                const maxResultLimit = positiveInteger(formValues.max_result_limit)

                if (formValues.enabled && !tenantColumnName) {
                    errors.tenant_column_name = 'Tenant column is required'
                }
                if (defaultTimeoutMs === null) {
                    errors.default_timeout_ms = 'Enter a positive integer'
                }
                if (maxTimeoutMs === null) {
                    errors.max_timeout_ms = 'Enter a positive integer'
                }
                if (maxResultLimit === null) {
                    errors.max_result_limit = 'Enter a positive integer'
                }
                if (defaultTimeoutMs !== null && maxTimeoutMs !== null && defaultTimeoutMs > maxTimeoutMs) {
                    errors.default_timeout_ms = 'Default timeout must be less than or equal to max timeout'
                }

                return errors
            },
            submit: async (formValues: TenantQueryConfigFormValues) => {
                if (!values.currentTeamId) {
                    lemonToast.error('Project is still loading')
                    return
                }

                const payload = formToRequestPayload(props.id, formValues)
                if (!payload) {
                    if (!props.id?.trim()) {
                        lemonToast.error('Connection is still loading')
                    }
                    return
                }

                try {
                    const response = await tenantQueryConfigCreate(String(values.currentTeamId), payload)
                    actions.loadTenantQueryConfigSuccess(response)
                    actions.resetTenantQueryConfigForm(configToForm(response))
                    actions.setTenantQueryConfigWarning(disabledTablesWarning(response.disabled_tables))
                    lemonToast.success('Multi-tenancy configuration saved')
                } catch (error: any) {
                    actions.setTenantQueryConfigError(tenantQueryConfigErrorMessage(error))
                }
            },
        },
        tenantQueryPlayground: {
            defaults: DEFAULT_TENANT_QUERY_PLAYGROUND_FORM,
            errors: (formValues: TenantQueryPlaygroundFormValues) => {
                const errors: DeepPartialMap<TenantQueryPlaygroundFormValues, ValidationErrorType> = {}
                const tenantValue = formValues.tenant_value.trim()
                const timeoutMs = formValues.timeout_ms === '' ? undefined : positiveInteger(formValues.timeout_ms)

                if (!tenantValue) {
                    errors.tenant_value = 'Tenant value is required'
                }
                if (!formValues.query.trim()) {
                    errors.query = 'Query is required'
                }
                if (timeoutMs === null) {
                    errors.timeout_ms = 'Enter a positive integer'
                }

                return errors
            },
            submit: async (formValues: TenantQueryPlaygroundFormValues) => {
                if (!values.currentTeamId) {
                    lemonToast.error('Project is still loading')
                    return
                }

                const payload = playgroundFormToRequestPayload(props.id, formValues)
                if (!payload) {
                    if (!props.id?.trim()) {
                        lemonToast.error('Connection is still loading')
                    }
                    return
                }

                try {
                    const response = await tenantQueryCreate(String(values.currentTeamId), payload)
                    actions.setTenantQueryPlaygroundResponse(response)
                    actions.setTenantQueryPlaygroundError(null)
                } catch (error: any) {
                    const errorMessage = error?.detail || error?.message || 'Unable to run tenant query'
                    actions.setTenantQueryPlaygroundError(errorMessage)
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values, props }) => ({
        loadTenantQueryConfigSuccess: ({ tenantQueryConfig }) => {
            if (!values.tenantQueryConfigFormChanged) {
                actions.resetTenantQueryConfigForm(configToForm(tenantQueryConfig))
            }
            if (!values.tenantQueryPlaygroundTouches.tenant_value) {
                actions.setTenantQueryPlaygroundValue(
                    'tenant_value',
                    defaultTenantValueForType(tenantQueryConfig?.tenant_column_type)
                )
            }
        },
        selectTenantQueryTableInPlayground: ({ tableName }) => {
            actions.setTenantQueryPlaygroundValue('query', selectAllQueryForTable(tableName))
            actions.setTenantQueryPlaygroundResponse(null)
            actions.setTenantQueryPlaygroundError(null)
            if (typeof window === 'undefined') {
                scrollToTenantQueryPlayground()
                actions.submitTenantQueryPlayground()
                return
            }

            window.setTimeout(() => {
                scrollToTenantQueryPlayground()
                actions.submitTenantQueryPlayground()
            })
        },
        saveTenantQueryTableColumnOverride: async ({ tableId, tableName, tenantColumnName }) => {
            if (!values.currentTeamId) {
                lemonToast.error('Project is still loading')
                return
            }

            const trimmedTenantColumnName = tenantColumnName.trim()
            if (!trimmedTenantColumnName) {
                lemonToast.error('Select a tenant column')
                return
            }

            const globalTenantColumnName = values.tenantQueryConfigForm.tenant_column_name.trim()
            const tenantColumnNamesByTable = { ...values.tenantQueryConfigForm.tenant_column_names_by_table }
            if (trimmedTenantColumnName === globalTenantColumnName) {
                delete tenantColumnNamesByTable[tableName]
            } else {
                tenantColumnNamesByTable[tableName] = trimmedTenantColumnName
            }

            const payload = formToRequestPayload(props.id, {
                ...values.tenantQueryConfigForm,
                tenant_column_names_by_table: tenantColumnNamesByTable,
            })
            if (!payload) {
                if (!props.id?.trim()) {
                    lemonToast.error('Connection is still loading')
                }
                return
            }

            actions.setSavingTenantQueryTableColumnOverride(tableId)
            try {
                const response = await tenantQueryConfigCreate(String(values.currentTeamId), payload)
                actions.loadTenantQueryConfigSuccess(response)
                actions.resetTenantQueryConfigForm(configToForm(response))
                actions.setTenantQueryConfigWarning(disabledTablesWarning(response.disabled_tables))
                lemonToast.success('Table setting saved')
            } catch (error: any) {
                actions.setTenantQueryConfigError(tenantQueryConfigErrorMessage(error))
            } finally {
                actions.setSavingTenantQueryTableColumnOverride(null)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTenantQueryConfig()
    }),
])
