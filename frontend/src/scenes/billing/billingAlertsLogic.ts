import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'

import {
    billingAlertsCheckNowCreate,
    billingAlertsCreate,
    billingAlertsDestinationsCreate,
    billingAlertsDestroy,
    billingAlertsEventsList,
    billingAlertsList,
    billingAlertsPartialUpdate,
} from '~/generated/core/api'
import type {
    BillingAlertConfigurationApi as GeneratedBillingAlertConfigurationApi,
    BillingAlertEventApi,
    MetricEnumApi,
    PatchedBillingAlertConfigurationApi,
    ThresholdTypeEnumApi,
} from '~/generated/core/api.schemas'
import type { UserBasicType } from '~/types'

import type { billingAlertsLogicType } from './billingAlertsLogicType'
import { billingLogic } from './billingLogic'

export type BillingAlertConfiguration = GeneratedBillingAlertConfigurationApi & {
    created_by?: UserBasicType | null
    updated_by?: UserBasicType | null
}

export enum BillingAlertCreationView {
    None = 'none',
    Wizard = 'wizard',
    Traditional = 'traditional',
}

export enum BillingAlertWizardStep {
    Destination = 'destination',
    Trigger = 'trigger',
    Configure = 'configure',
}

export type BillingAlertTriggerKey = 'spend_relative_increase' | 'spend_absolute_value' | 'usage_relative_increase'
export type BillingAlertDestinationKey = 'slack'

export interface BillingAlertTrigger {
    key: BillingAlertTriggerKey
    name: string
    description: string
}

export interface BillingAlertListFilters {
    search: string
    createdBy: number | null
    showPaused: boolean
}

export interface BillingAlertForm {
    name: string
    metric: MetricEnumApi
    threshold_type: ThresholdTypeEnumApi
    threshold_percentage: number
    threshold_value: number | undefined
    minimum_value: number
    baseline_window_days: number
    evaluation_delay_hours: number
    check_interval_hours: number
    cooldown_hours: number
}

const DEFAULT_LIST_FILTERS: BillingAlertListFilters = {
    search: '',
    createdBy: null,
    showPaused: false,
}

export const BILLING_ALERT_TRIGGERS: BillingAlertTrigger[] = [
    {
        key: 'spend_relative_increase',
        name: 'Daily spend increases',
        description: 'Notify when daily spend is up by a percentage against the recent baseline.',
    },
    {
        key: 'spend_absolute_value',
        name: 'Daily spend crosses an amount',
        description: 'Notify when daily spend goes above a fixed dollar amount.',
    },
    {
        key: 'usage_relative_increase',
        name: 'Daily usage increases',
        description: 'Notify when total daily usage is up by a percentage against the recent baseline.',
    },
]

export const DEFAULT_BILLING_ALERT_FORM: BillingAlertForm = {
    name: '',
    metric: 'spend',
    threshold_type: 'relative_increase',
    threshold_percentage: 50,
    threshold_value: undefined,
    minimum_value: 0,
    baseline_window_days: 7,
    evaluation_delay_hours: 6,
    check_interval_hours: 24,
    cooldown_hours: 24,
}

function triggerDefaults(triggerKey: BillingAlertTriggerKey): Partial<BillingAlertForm> {
    if (triggerKey === 'spend_absolute_value') {
        return {
            name: 'Daily spend threshold',
            metric: 'spend',
            threshold_type: 'absolute_value',
            threshold_value: 100,
            threshold_percentage: 50,
        }
    }
    if (triggerKey === 'usage_relative_increase') {
        return {
            name: 'Daily usage increase',
            metric: 'usage',
            threshold_type: 'relative_increase',
            threshold_percentage: 50,
            threshold_value: undefined,
        }
    }
    return {
        name: 'Daily spend increase',
        metric: 'spend',
        threshold_type: 'relative_increase',
        threshold_percentage: 50,
        threshold_value: undefined,
    }
}

function apiMessage(error: unknown): string {
    return error instanceof ApiError ? error.detail || 'Request failed.' : 'Request failed.'
}

function splitSlackChannel(slackChannel: string): { channelId: string; channelName: string } {
    const [channelId, channelName] = slackChannel.split('|#')
    return { channelId, channelName: channelName ?? '' }
}

function createPayload(form: BillingAlertForm): Parameters<typeof billingAlertsCreate>[1] {
    return {
        metric: form.metric,
        threshold_type: form.threshold_type,
        minimum_value: String(form.minimum_value),
        baseline_window_days: form.baseline_window_days,
        evaluation_delay_hours: form.evaluation_delay_hours,
        check_interval_hours: form.check_interval_hours,
        cooldown_hours: form.cooldown_hours,
        name: form.name.trim(),
        threshold_percentage: form.threshold_type === 'relative_increase' ? String(form.threshold_percentage) : null,
        threshold_value: form.threshold_type === 'relative_increase' ? null : String(form.threshold_value ?? 0),
    }
}

export const billingAlertsLogic = kea<billingAlertsLogicType>([
    path(['scenes', 'billing', 'billingAlertsLogic']),

    connect(() => ({
        values: [billingLogic, ['currentOrganization', 'canAccessBilling']],
    })),

    actions({
        setCreationView: (view: BillingAlertCreationView) => ({ view }),
        setWizardStep: (step: BillingAlertWizardStep) => ({ step }),
        setSelectedDestinationKey: (destinationKey: BillingAlertDestinationKey) => ({ destinationKey }),
        selectTrigger: (triggerKey: BillingAlertTriggerKey) => ({ triggerKey }),
        setFilters: (filters: Partial<BillingAlertListFilters>) => ({ filters }),
        resetFilters: true,
        setFormValue: (key: keyof BillingAlertForm, value: BillingAlertForm[keyof BillingAlertForm]) => ({
            key,
            value,
        }),
        resetCreation: true,
        createAlert: true,
        updateAlert: (alert: BillingAlertConfiguration, updates: PatchedBillingAlertConfigurationApi) => ({
            alert,
            updates,
        }),
        deleteAlert: (alert: BillingAlertConfiguration) => ({ alert }),
        checkNow: (alert: BillingAlertConfiguration) => ({ alert }),
        loadEvents: (alertId: string) => ({ alertId }),
        setEvents: (alertId: string, events: BillingAlertEventApi[]) => ({ alertId, events }),
        setDestinationAlertId: (alertId: string | null) => ({ alertId }),
        setSlackIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setSlackChannel: (slackChannel: string | null) => ({ slackChannel }),
        createSlackDestination: true,
        setSaving: (saving: boolean) => ({ saving }),
        setDestinationSaving: (saving: boolean) => ({ saving }),
        setCheckingAlertId: (alertId: string | null) => ({ alertId }),
        setUpdatingAlertId: (alertId: string, updating: boolean) => ({ alertId, updating }),
    }),

    reducers({
        creationView: [
            BillingAlertCreationView.None as BillingAlertCreationView,
            {
                setCreationView: (_, { view }) => view,
                resetCreation: () => BillingAlertCreationView.None,
            },
        ],
        wizardStep: [
            BillingAlertWizardStep.Destination as BillingAlertWizardStep,
            {
                setCreationView: () => BillingAlertWizardStep.Destination,
                setWizardStep: (_, { step }) => step,
                setSelectedDestinationKey: () => BillingAlertWizardStep.Trigger,
                selectTrigger: () => BillingAlertWizardStep.Configure,
                resetCreation: () => BillingAlertWizardStep.Destination,
            },
        ],
        selectedDestinationKey: [
            'slack' as BillingAlertDestinationKey,
            {
                setSelectedDestinationKey: (_, { destinationKey }) => destinationKey,
                resetCreation: () => 'slack' as BillingAlertDestinationKey,
            },
        ],
        selectedTriggerKey: [
            'spend_relative_increase' as BillingAlertTriggerKey,
            {
                selectTrigger: (_, { triggerKey }) => triggerKey,
                resetCreation: () => 'spend_relative_increase' as BillingAlertTriggerKey,
            },
        ],
        form: [
            DEFAULT_BILLING_ALERT_FORM as BillingAlertForm,
            {
                setFormValue: (state, { key, value }) => ({ ...state, [key]: value }),
                selectTrigger: (state, { triggerKey }) => {
                    const defaults = triggerDefaults(triggerKey)
                    return {
                        ...state,
                        ...defaults,
                        name: state.name.trim() ? state.name : (defaults.name ?? state.name),
                    }
                },
                resetCreation: () => DEFAULT_BILLING_ALERT_FORM,
            },
        ],
        filters: [
            DEFAULT_LIST_FILTERS as BillingAlertListFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                resetFilters: () => DEFAULT_LIST_FILTERS,
            },
        ],
        eventsByAlert: [
            {} as Record<string, BillingAlertEventApi[]>,
            {
                setEvents: (state, { alertId, events }) => ({ ...state, [alertId]: events }),
            },
        ],
        destinationAlertId: [
            null as string | null,
            {
                setDestinationAlertId: (_, { alertId }) => alertId,
                resetCreation: () => null,
            },
        ],
        slackIntegrationId: [
            null as number | null,
            {
                setSlackIntegrationId: (_, { integrationId }) => integrationId,
                resetCreation: () => null,
            },
        ],
        slackChannel: [
            null as string | null,
            {
                setSlackChannel: (_, { slackChannel }) => slackChannel,
                setSlackIntegrationId: () => null,
                resetCreation: () => null,
            },
        ],
        saving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
        destinationSaving: [
            false,
            {
                setDestinationSaving: (_, { saving }) => saving,
            },
        ],
        checkingAlertId: [
            null as string | null,
            {
                setCheckingAlertId: (_, { alertId }) => alertId,
            },
        ],
        updatingAlertIds: [
            new Set<string>(),
            {
                setUpdatingAlertId: (state, { alertId, updating }) =>
                    updating ? new Set([...state, alertId]) : new Set([...state].filter((id) => id !== alertId)),
            },
        ],
    }),

    loaders(({ values }) => ({
        alerts: [
            [] as BillingAlertConfiguration[],
            {
                loadAlerts: async () => {
                    const organizationId = values.currentOrganization?.id
                    if (!organizationId || !values.canAccessBilling) {
                        return []
                    }
                    const response = await billingAlertsList(organizationId, { limit: 500 })
                    return response.results as BillingAlertConfiguration[]
                },
            },
        ],
    })),

    selectors({
        filteredAlerts: [
            (s) => [s.alerts, s.filters],
            (alerts: BillingAlertConfiguration[], filters: BillingAlertListFilters): BillingAlertConfiguration[] => {
                const search = filters.search.trim().toLowerCase()
                return alerts.filter((alert) => {
                    if (!filters.showPaused && !alert.enabled) {
                        return false
                    }
                    if (filters.createdBy && alert.created_by?.id !== filters.createdBy) {
                        return false
                    }
                    if (search) {
                        const haystack = `${alert.name} ${alert.description ?? ''}`.toLowerCase()
                        if (!haystack.includes(search)) {
                            return false
                        }
                    }
                    return true
                })
            },
        ],
        hiddenAlertCount: [
            (s) => [s.alerts, s.filteredAlerts],
            (alerts: BillingAlertConfiguration[], filteredAlerts: BillingAlertConfiguration[]): number =>
                alerts.length - filteredAlerts.length,
        ],
        canSubmit: [
            (s) => [s.form, s.selectedDestinationKey, s.slackIntegrationId, s.slackChannel],
            (
                form: BillingAlertForm,
                selectedDestinationKey: BillingAlertDestinationKey,
                slackIntegrationId: number | null,
                slackChannel: string | null
            ): boolean => {
                const hasThreshold =
                    form.threshold_type === 'relative_increase'
                        ? form.threshold_percentage > 0
                        : form.threshold_value !== undefined
                const hasDestination =
                    selectedDestinationKey !== 'slack' || (!!slackIntegrationId && !!slackChannel?.trim())
                return !!form.name.trim() && hasThreshold && hasDestination
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createAlert: async () => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || !values.canSubmit || values.saving) {
                return
            }

            actions.setSaving(true)
            try {
                const created = await billingAlertsCreate(organizationId, createPayload(values.form))
                if (values.selectedDestinationKey === 'slack' && values.slackIntegrationId && values.slackChannel) {
                    const { channelId, channelName } = splitSlackChannel(values.slackChannel)
                    await billingAlertsDestinationsCreate(organizationId, created.id, {
                        type: 'slack',
                        slack_workspace_id: values.slackIntegrationId,
                        slack_channel_id: channelId,
                        slack_channel_name: channelName,
                    })
                }
                lemonToast.success('Billing alert created.')
                actions.resetCreation()
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setSaving(false)
            }
        },
        updateAlert: async ({ alert, updates }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.updatingAlertIds.has(alert.id)) {
                return
            }

            actions.setUpdatingAlertId(alert.id, true)
            try {
                await billingAlertsPartialUpdate(organizationId, alert.id, updates)
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setUpdatingAlertId(alert.id, false)
            }
        },
        deleteAlert: async ({ alert }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.updatingAlertIds.has(alert.id)) {
                return
            }

            actions.setUpdatingAlertId(alert.id, true)
            try {
                await billingAlertsDestroy(organizationId, alert.id)
                lemonToast.success('Billing alert deleted.')
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setUpdatingAlertId(alert.id, false)
            }
        },
        checkNow: async ({ alert }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.checkingAlertId) {
                return
            }

            actions.setCheckingAlertId(alert.id)
            try {
                await billingAlertsCheckNowCreate(organizationId, alert.id)
                lemonToast.success('Billing alert checked.')
                actions.loadAlerts()
                actions.loadEvents(alert.id)
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setCheckingAlertId(null)
            }
        },
        loadEvents: async ({ alertId }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId) {
                return
            }

            try {
                const response = await billingAlertsEventsList(organizationId, alertId, { limit: 5 })
                actions.setEvents(alertId, response.results)
            } catch (error) {
                lemonToast.error(apiMessage(error))
            }
        },
        createSlackDestination: async () => {
            const organizationId = values.currentOrganization?.id
            if (
                !organizationId ||
                !values.destinationAlertId ||
                !values.slackIntegrationId ||
                !values.slackChannel ||
                values.destinationSaving
            ) {
                return
            }

            const { channelId, channelName } = splitSlackChannel(values.slackChannel)
            actions.setDestinationSaving(true)
            try {
                await billingAlertsDestinationsCreate(organizationId, values.destinationAlertId, {
                    type: 'slack',
                    slack_workspace_id: values.slackIntegrationId,
                    slack_channel_id: channelId,
                    slack_channel_name: channelName,
                })
                lemonToast.success('Slack destination added.')
                actions.setDestinationAlertId(null)
                actions.setSlackChannel(null)
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setDestinationSaving(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAlerts()
    }),
])
