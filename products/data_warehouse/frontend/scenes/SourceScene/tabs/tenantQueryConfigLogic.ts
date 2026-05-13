import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
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
    default_timeout_ms: number | string
    max_timeout_ms: number | string
    max_result_limit: number | string
}

export interface TenantQueryPlaygroundFormValues {
    tenant_value: string
    query: string
    timeout_ms: number | string | ''
}

const DEFAULT_TENANT_QUERY_CONFIG_FORM: TenantQueryConfigFormValues = {
    enabled: false,
    tenant_column_name: '',
    default_timeout_ms: 30_000,
    max_timeout_ms: 120_000,
    max_result_limit: 100_000,
}

const DEFAULT_TENANT_QUERY_PLAYGROUND_FORM: TenantQueryPlaygroundFormValues = {
    tenant_value: '',
    query: 'select * from system.tables',
    timeout_ms: '',
}

function configToForm(config: TenantQueryConfigResponseApi | null): TenantQueryConfigFormValues {
    if (!config) {
        return DEFAULT_TENANT_QUERY_CONFIG_FORM
    }

    return {
        enabled: config.enabled,
        tenant_column_name: config.tenant_column_name ?? '',
        default_timeout_ms: config.default_timeout_ms,
        max_timeout_ms: config.max_timeout_ms,
        max_result_limit: config.max_result_limit,
    }
}

function positiveInteger(value: number | string): number | null {
    const parsedValue = typeof value === 'number' ? value : Number(value)

    if (!Number.isFinite(parsedValue) || !Number.isInteger(parsedValue) || parsedValue < 1) {
        return null
    }

    return parsedValue
}

function formToRequestPayload(
    connectionId: string,
    formValues: TenantQueryConfigFormValues
): TenantQueryConfigRequestApi | null {
    const defaultTimeoutMs = positiveInteger(formValues.default_timeout_ms)
    const maxTimeoutMs = positiveInteger(formValues.max_timeout_ms)
    const maxResultLimit = positiveInteger(formValues.max_result_limit)

    if (defaultTimeoutMs === null || maxTimeoutMs === null || maxResultLimit === null) {
        return null
    }

    return {
        connection_id: connectionId,
        enabled: formValues.enabled,
        tenant_column_name: formValues.tenant_column_name.trim() || null,
        default_timeout_ms: defaultTimeoutMs,
        max_timeout_ms: maxTimeoutMs,
        max_result_limit: maxResultLimit,
    }
}

function playgroundFormToRequestPayload(
    connectionId: string,
    formValues: TenantQueryPlaygroundFormValues
): TenantQueryRequestApi | null {
    const timeoutMs = formValues.timeout_ms === '' ? undefined : positiveInteger(formValues.timeout_ms)
    if (timeoutMs === null) {
        return null
    }

    return {
        connection_id: connectionId,
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
    }),
    forms(({ props, values, actions }) => ({
        tenantQueryConfigForm: {
            defaults: DEFAULT_TENANT_QUERY_CONFIG_FORM,
            errors: (formValues: TenantQueryConfigFormValues) => {
                const errors: Partial<Record<keyof TenantQueryConfigFormValues, string>> = {}
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
                const errors: Partial<Record<keyof TenantQueryPlaygroundFormValues, string>> = {}
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
    listeners(({ actions, values }) => ({
        loadTenantQueryConfigSuccess: ({ tenantQueryConfig }) => {
            if (!values.tenantQueryConfigFormChanged) {
                actions.resetTenantQueryConfigForm(configToForm(tenantQueryConfig))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTenantQueryConfig()
    }),
])
