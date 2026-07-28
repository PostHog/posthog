import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import type { OrganizationType } from '~/types'

import { billingAlertRequestError, offsetFromPageLink } from './billingAlertUtils'
import { billingAlertsCheckNowCreate, billingAlertsDestroy, billingAlertsList } from './generated/api'
import type { BillingAlertConfigurationApi, PaginatedBillingAlertConfigurationListApi } from './generated/api.schemas'

const EMPTY_ALERTS_PAGE: PaginatedBillingAlertConfigurationListApi = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

export function mergeUniqueAlerts(
    current: BillingAlertConfigurationApi[],
    incoming: BillingAlertConfigurationApi[]
): BillingAlertConfigurationApi[] {
    const knownIds = new Set(current.map((alert) => alert.id))
    return [
        ...current,
        ...incoming.filter((alert) => {
            if (knownIds.has(alert.id)) {
                return false
            }
            knownIds.add(alert.id)
            return true
        }),
    ]
}

export const CHECK_NOW_CONFIRMATION_DESCRIPTION =
    'This evaluates live billing data and may send Slack, Microsoft Teams, or webhook notifications.'

export function openBillingAlertCheckNowConfirmation(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Check billing alert now?',
        description: CHECK_NOW_CONFIRMATION_DESCRIPTION,
        primaryButton: {
            children: 'Check now',
            onClick: onConfirm,
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export interface billingAlertsLogicValues {
    canAccessBilling: boolean
    currentOrganization: OrganizationType | null
    alertsPage: PaginatedBillingAlertConfigurationListApi
    alertsPageLoading: boolean
    alerts: BillingAlertConfigurationApi[]
    selectedAlert: BillingAlertConfigurationApi | null
    isEditorOpen: boolean
    checkingAlertId: string | null
    deletingAlertIds: Set<string>
}

export interface billingAlertsLogicActions {
    loadAlerts: () => void
    loadAlertsSuccess: (alertsPage: PaginatedBillingAlertConfigurationListApi) => {
        alertsPage: PaginatedBillingAlertConfigurationListApi
    }
    loadAlertsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadMoreAlerts: () => void
    loadMoreAlertsSuccess: (alertsPage: PaginatedBillingAlertConfigurationListApi) => {
        alertsPage: PaginatedBillingAlertConfigurationListApi
    }
    loadMoreAlertsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    createAlert: () => { value: true }
    editAlert: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    alertUpdated: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    closeEditor: () => { value: true }
    checkNow: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    runCheckNow: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    deleteAlert: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
    setCheckingAlertId: (alertId: string | null) => { alertId: string | null }
    setDeletingAlertId: (alertId: string, deleting: boolean) => { alertId: string; deleting: boolean }
    resetOrganizationState: () => { value: true }
    loadCurrentOrganizationSuccess: (
        currentOrganization: OrganizationType | null,
        payload?: any
    ) => {
        currentOrganization: OrganizationType | null
        payload?: any
    }
}

export type billingAlertsLogicType = MakeLogicType<billingAlertsLogicValues, billingAlertsLogicActions>

export const billingAlertsLogic = kea<billingAlertsLogicType>([
    path(['products', 'billingAlerts', 'frontend', 'billingAlertsLogic']),
    connect({
        values: [billingLogic, ['canAccessBilling', 'currentOrganization']],
        actions: [organizationLogic, ['loadCurrentOrganizationSuccess']],
    }),
    actions({
        createAlert: true,
        editAlert: (alert: BillingAlertConfigurationApi) => ({ alert }),
        alertUpdated: (alert: BillingAlertConfigurationApi) => ({ alert }),
        closeEditor: true,
        checkNow: (alert: BillingAlertConfigurationApi) => ({ alert }),
        runCheckNow: (alert: BillingAlertConfigurationApi) => ({ alert }),
        deleteAlert: (alert: BillingAlertConfigurationApi) => ({ alert }),
        setCheckingAlertId: (alertId: string | null) => ({ alertId }),
        setDeletingAlertId: (alertId: string, deleting: boolean) => ({ alertId, deleting }),
        resetOrganizationState: true,
    }),
    reducers({
        selectedAlert: [
            null as BillingAlertConfigurationApi | null,
            {
                createAlert: () => null,
                editAlert: (_, { alert }) => alert,
                alertUpdated: (state, { alert }) => (state?.id === alert.id ? alert : state),
                resetOrganizationState: () => null,
            },
        ],
        isEditorOpen: [
            false,
            {
                createAlert: () => true,
                editAlert: () => true,
                closeEditor: () => false,
                resetOrganizationState: () => false,
            },
        ],
        checkingAlertId: [
            null as string | null,
            { setCheckingAlertId: (_, { alertId }) => alertId, resetOrganizationState: () => null },
        ],
        deletingAlertIds: [
            new Set<string>(),
            {
                setDeletingAlertId: (state, { alertId, deleting }) =>
                    deleting ? new Set([...state, alertId]) : new Set([...state].filter((id) => id !== alertId)),
                resetOrganizationState: () => new Set(),
            },
        ],
    }),
    loaders(({ values }) => ({
        alertsPage: [
            EMPTY_ALERTS_PAGE,
            {
                loadAlerts: async (_, breakpoint) => {
                    if (!values.currentOrganization?.id || !values.canAccessBilling) {
                        return EMPTY_ALERTS_PAGE
                    }
                    await breakpoint()
                    const page = await billingAlertsList(values.currentOrganization.id, { limit: 30 })
                    await breakpoint()
                    return page
                },
                loadMoreAlerts: async (_, breakpoint) => {
                    if (!values.currentOrganization?.id || !values.alertsPage.next) {
                        return values.alertsPage
                    }
                    await breakpoint()
                    const nextPage = await billingAlertsList(values.currentOrganization.id, {
                        limit: 30,
                        offset: offsetFromPageLink(values.alertsPage.next, values.alertsPage.results.length),
                    })
                    await breakpoint()
                    return {
                        ...nextPage,
                        results: mergeUniqueAlerts(values.alertsPage.results, nextPage.results),
                    }
                },
            },
        ],
    })),
    selectors({
        alerts: [
            (selectors) => [selectors.alertsPage],
            (alertsPage: PaginatedBillingAlertConfigurationListApi): BillingAlertConfigurationApi[] =>
                alertsPage.results,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadAlertsFailure: ({ error, errorObject }) => {
            lemonToast.error(billingAlertRequestError(errorObject ?? error))
        },
        loadMoreAlertsFailure: ({ error, errorObject }) => {
            lemonToast.error(billingAlertRequestError(errorObject ?? error))
        },
        loadCurrentOrganizationSuccess: () => {
            actions.resetOrganizationState()
            actions.loadAlertsSuccess(EMPTY_ALERTS_PAGE)
            actions.loadAlerts()
        },
        checkNow: ({ alert }) => {
            openBillingAlertCheckNowConfirmation(() => actions.runCheckNow(alert))
        },
        runCheckNow: async ({ alert }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.checkingAlertId) {
                return
            }
            actions.setCheckingAlertId(alert.id)
            try {
                const result = await billingAlertsCheckNowCreate(organizationId, alert.id)
                if (values.currentOrganization?.id !== organizationId) {
                    return
                }
                lemonToast.success(result.event.kind === 'firing' ? 'Billing alert fired.' : 'Billing alert checked.')
                actions.closeEditor()
                actions.loadAlerts()
            } catch (error) {
                if (values.currentOrganization?.id === organizationId) {
                    lemonToast.error(billingAlertRequestError(error))
                }
            } finally {
                if (values.currentOrganization?.id === organizationId && values.checkingAlertId === alert.id) {
                    actions.setCheckingAlertId(null)
                }
            }
        },
        deleteAlert: async ({ alert }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.deletingAlertIds.has(alert.id)) {
                return
            }
            actions.setDeletingAlertId(alert.id, true)
            try {
                await billingAlertsDestroy(organizationId, alert.id)
                if (values.currentOrganization?.id !== organizationId) {
                    return
                }
                lemonToast.success('Billing alert deleted.')
                actions.closeEditor()
                actions.loadAlerts()
            } catch (error) {
                if (values.currentOrganization?.id === organizationId) {
                    lemonToast.error(billingAlertRequestError(error))
                }
            } finally {
                if (values.currentOrganization?.id === organizationId) {
                    actions.setDeletingAlertId(alert.id, false)
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAlerts()
    }),
])
