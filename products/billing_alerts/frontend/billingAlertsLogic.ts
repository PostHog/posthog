import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'

import type { OrganizationType } from '~/types'

import { billingAlertsCheckNowCreate, billingAlertsDestroy, billingAlertsList } from './generated/api'
import type { BillingAlertConfigurationApi } from './generated/api.schemas'

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        return error.detail || 'Request failed.'
    }
    return error instanceof Error ? error.message : 'Request failed.'
}

export interface billingAlertsLogicValues {
    canAccessBilling: boolean
    currentOrganization: OrganizationType | null
    alerts: BillingAlertConfigurationApi[]
    alertsLoading: boolean
    selectedAlert: BillingAlertConfigurationApi | null
    isEditorOpen: boolean
    checkingAlertId: string | null
    deletingAlertIds: Set<string>
}

export interface billingAlertsLogicActions {
    loadAlerts: () => void
    loadAlertsSuccess: (alerts: BillingAlertConfigurationApi[]) => { alerts: BillingAlertConfigurationApi[] }
    loadAlertsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    createAlert: () => { value: true }
    editAlert: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    closeEditor: () => { value: true }
    checkNow: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    deleteAlert: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    setCheckingAlertId: (alertId: string | null) => { alertId: string | null }
    setDeletingAlertId: (alertId: string, deleting: boolean) => { alertId: string; deleting: boolean }
}

export type billingAlertsLogicType = MakeLogicType<billingAlertsLogicValues, billingAlertsLogicActions>

export const billingAlertsLogic = kea<billingAlertsLogicType>([
    path(['products', 'billingAlerts', 'frontend', 'billingAlertsLogic']),
    connect({
        values: [billingLogic, ['canAccessBilling', 'currentOrganization']],
    }),
    actions({
        createAlert: true,
        editAlert: (alert: BillingAlertConfigurationApi) => ({ alert }),
        closeEditor: true,
        checkNow: (alert: BillingAlertConfigurationApi) => ({ alert }),
        deleteAlert: (alert: BillingAlertConfigurationApi) => ({ alert }),
        setCheckingAlertId: (alertId: string | null) => ({ alertId }),
        setDeletingAlertId: (alertId: string, deleting: boolean) => ({ alertId, deleting }),
    }),
    reducers({
        selectedAlert: [
            null as BillingAlertConfigurationApi | null,
            {
                createAlert: () => null,
                editAlert: (_, { alert }) => alert,
            },
        ],
        isEditorOpen: [
            false,
            {
                createAlert: () => true,
                editAlert: () => true,
                closeEditor: () => false,
            },
        ],
        checkingAlertId: [null as string | null, { setCheckingAlertId: (_, { alertId }) => alertId }],
        deletingAlertIds: [
            new Set<string>(),
            {
                setDeletingAlertId: (state, { alertId, deleting }) =>
                    deleting ? new Set([...state, alertId]) : new Set([...state].filter((id) => id !== alertId)),
            },
        ],
    }),
    loaders(({ values }) => ({
        alerts: [
            [] as BillingAlertConfigurationApi[],
            {
                loadAlerts: async () => {
                    if (!values.currentOrganization?.id || !values.canAccessBilling) {
                        return []
                    }
                    const response = await billingAlertsList(values.currentOrganization.id, { limit: 100 })
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadAlertsFailure: ({ error, errorObject }) => {
            lemonToast.error(errorMessage(errorObject ?? error))
        },
        checkNow: async ({ alert }) => {
            if (!values.currentOrganization?.id || values.checkingAlertId) {
                return
            }
            actions.setCheckingAlertId(alert.id)
            try {
                const result = await billingAlertsCheckNowCreate(values.currentOrganization.id, alert.id)
                lemonToast.success(result.event.kind === 'firing' ? 'Billing alert fired.' : 'Billing alert checked.')
                actions.closeEditor()
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(errorMessage(error))
            } finally {
                actions.setCheckingAlertId(null)
            }
        },
        deleteAlert: async ({ alert }) => {
            if (!values.currentOrganization?.id || values.deletingAlertIds.has(alert.id)) {
                return
            }
            actions.setDeletingAlertId(alert.id, true)
            try {
                await billingAlertsDestroy(values.currentOrganization.id, alert.id)
                lemonToast.success('Billing alert deleted.')
                actions.closeEditor()
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(errorMessage(error))
            } finally {
                actions.setDeletingAlertId(alert.id, false)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAlerts()
    }),
])
