import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { UserBasicType } from '~/types'

import {
    billingAlertsCheckNowCreate,
    billingAlertsCreate,
    billingAlertsDestinationsCreate,
    billingAlertsDestinationsDeleteCreate,
    billingAlertsDestroy,
    billingAlertsEventsList,
    billingAlertsList,
    billingAlertsPartialUpdate,
} from 'products/billing_alerts/frontend/generated/api'
import type {
    BillingAlertCreateDestinationApi,
    BillingAlertConfigurationApi as GeneratedBillingAlertConfigurationApi,
    BillingAlertEventApi,
    BillingAlertMetricEnumApi,
    PatchedBillingAlertConfigurationApi,
    ThresholdTypeEnumApi,
} from 'products/billing_alerts/frontend/generated/api.schemas'

import type { OrganizationType } from '../../../frontend/src/types'
import { BILLING_ALERT_FORM_LIMITS } from './billingAlertFields'
import type { BillingAlertDestinationSummaryApi } from './generated/api.schemas'

export type BillingAlertConfiguration = GeneratedBillingAlertConfigurationApi & {
    created_by?: UserBasicType | null
    updated_by?: UserBasicType | null
}
export type BillingAlertDestination = NonNullable<BillingAlertConfiguration['destinations']>[number]

export enum BillingAlertCreationView {
    None = 'none',
    Wizard = 'wizard',
}

export enum BillingAlertWizardStep {
    Destination = 'destination',
    Trigger = 'trigger',
    Configure = 'configure',
}

export type BillingAlertTriggerKey = 'spend_relative_increase' | 'spend_absolute_value' | 'usage_relative_increase'
export type BillingAlertDestinationKey = 'slack' | 'webhook' | 'teams'

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
    metric: BillingAlertMetricEnumApi
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

function numberInRange(value: number | undefined, limits: { min: number; max?: number }): boolean {
    return value !== undefined && value >= limits.min && (limits.max === undefined || value <= limits.max)
}

function formValuesInRange(form: BillingAlertForm): boolean {
    return Object.entries(BILLING_ALERT_FORM_LIMITS).every(([key, limits]) => {
        if (key === 'threshold_value' && form.threshold_type === 'relative_increase') {
            return true
        }
        return numberInRange(form[key as keyof BillingAlertForm] as number | undefined, limits)
    })
}

export function isBillingAlertHiddenByPausedFilter(alert: BillingAlertConfiguration, showPaused: boolean): boolean {
    return !showPaused && !alert.enabled && alert.state !== 'broken'
}

function firstApiMessage(value: unknown): string | null {
    if (typeof value === 'string') {
        return value
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            const message = firstApiMessage(item)
            if (message) {
                return message
            }
        }
        return null
    }
    if (value && typeof value === 'object') {
        for (const [key, item] of Object.entries(value)) {
            const message = firstApiMessage(item)
            if (message) {
                return key === 'non_field_errors' || key === 'detail' ? message : `${key}: ${message}`
            }
        }
    }
    return null
}

function apiMessage(error: unknown): string {
    return error instanceof ApiError
        ? error.detail || firstApiMessage(error.data) || 'Request failed.'
        : 'Request failed.'
}

function splitSlackChannel(slackChannel: string): { channelId: string; channelName: string } {
    const [channelId, channelName] = slackChannel.split('|#')
    return { channelId, channelName: channelName ?? '' }
}

function isValidHttpsUrl(value: string | null): boolean {
    const trimmed = value?.trim()
    return !!trimmed && URL.canParse(trimmed) && new URL(trimmed).protocol === 'https:'
}

function destinationPayload({
    destinationKey,
    slackIntegrationId,
    slackChannel,
    webhookUrl,
}: {
    destinationKey: BillingAlertDestinationKey
    slackIntegrationId: number | null
    slackChannel: string | null
    webhookUrl: string
}): BillingAlertCreateDestinationApi | null {
    if (destinationKey === 'slack') {
        if (!slackIntegrationId || !slackChannel?.trim()) {
            return null
        }
        const { channelId, channelName } = splitSlackChannel(slackChannel)
        return {
            type: 'slack',
            slack_workspace_id: slackIntegrationId,
            slack_channel_id: channelId,
            slack_channel_name: channelName,
        }
    }

    if (!isValidHttpsUrl(webhookUrl)) {
        return null
    }

    return {
        type: destinationKey,
        webhook_url: webhookUrl.trim(),
    }
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertsLogicValues {
    canAccessBilling: boolean // billingLogic
    currentOrganization: OrganizationType | null // billingLogic
    currentTeamId: number | null // teamLogic
    alerts: BillingAlertConfiguration[]
    alertsLoadFailed: boolean
    alertsLoading: boolean
    canCreateDestination: boolean
    canSubmit: boolean
    checkingAlertId: string | null
    creationView: BillingAlertCreationView
    destinationAlert: BillingAlertConfiguration | null
    destinationAlertId: string | null
    destinationSaving: boolean
    destinationTypeExists: boolean
    eventsByAlert: Record<string, BillingAlertEventApi[]>
    eventsLoadFailedIds: Set<string>
    filteredAlerts: BillingAlertConfiguration[]
    filters: BillingAlertListFilters
    form: BillingAlertForm
    hiddenAlertCount: number
    saving: boolean
    selectedDestinationKey: BillingAlertDestinationKey
    selectedTriggerKey: BillingAlertTriggerKey
    slackChannel: string | null
    slackExecutionTeamMismatch: boolean
    slackIntegrationId: number | null
    updatingAlertIds: Set<string>
    webhookUrl: string
    wizardStep: BillingAlertWizardStep
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertsLogicActions {
    checkNow: (alert: BillingAlertConfiguration) => {
        alert: BillingAlertConfiguration
    }
    createAlert: () => {
        value: true
    }
    createDestination: () => {
        value: true
    }
    deleteAlert: (alert: BillingAlertConfiguration) => {
        alert: BillingAlertConfiguration
    }
    deleteDestination: (
        alert: BillingAlertConfiguration,
        destination: BillingAlertDestination
    ) => {
        alert: BillingAlertConfiguration
        destination: BillingAlertDestinationSummaryApi
    }
    loadAlerts: () => any
    loadAlertsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAlertsSuccess: (
        alerts: BillingAlertConfiguration[],
        payload?: any
    ) => {
        alerts: BillingAlertConfiguration[]
        payload?: any
    }
    loadEvents: (alertId: string) => {
        alertId: string
    }
    openDestinationPanel: (alertId: string) => {
        alertId: string
    }
    resetCreation: () => {
        value: true
    }
    resetFilters: () => {
        value: true
    }
    selectDestination: (destinationKey: BillingAlertDestinationKey) => {
        destinationKey: BillingAlertDestinationKey
    }
    selectTrigger: (triggerKey: BillingAlertTriggerKey) => {
        triggerKey: BillingAlertTriggerKey
    }
    setAlertsLoadFailed: (failed: boolean) => {
        failed: boolean
    }
    setCheckingAlertId: (alertId: string | null) => {
        alertId: string | null
    }
    setCreationView: (view: BillingAlertCreationView) => {
        view: BillingAlertCreationView
    }
    setDestinationAlertId: (alertId: string | null) => {
        alertId: string | null
    }
    setDestinationSaving: (saving: boolean) => {
        saving: boolean
    }
    setEvents: (
        alertId: string,
        events: BillingAlertEventApi[]
    ) => {
        alertId: string
        events: BillingAlertEventApi[]
    }
    setEventsFailed: (alertId: string) => {
        alertId: string
    }
    setFilters: (filters: Partial<BillingAlertListFilters>) => {
        filters: Partial<BillingAlertListFilters>
    }
    setFormValue: (
        key: keyof BillingAlertForm,
        value: BillingAlertForm[keyof BillingAlertForm]
    ) => {
        key: keyof BillingAlertForm
        value: number | string | undefined
    }
    setSaving: (saving: boolean) => {
        saving: boolean
    }
    setSelectedDestinationKey: (destinationKey: BillingAlertDestinationKey) => {
        destinationKey: BillingAlertDestinationKey
    }
    setSlackChannel: (slackChannel: string | null) => {
        slackChannel: string | null
    }
    setSlackIntegrationId: (integrationId: number | null) => {
        integrationId: number | null
    }
    setUpdatingAlertId: (
        alertId: string,
        updating: boolean
    ) => {
        alertId: string
        updating: boolean
    }
    setWebhookUrl: (webhookUrl: string) => {
        webhookUrl: string
    }
    setWizardStep: (step: BillingAlertWizardStep) => {
        step: BillingAlertWizardStep
    }
    updateAlert: (
        alert: BillingAlertConfiguration,
        updates: PatchedBillingAlertConfigurationApi
    ) => {
        alert: BillingAlertConfiguration
        updates: PatchedBillingAlertConfigurationApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        destinationAlert: (
            alerts: BillingAlertConfiguration[],
            destinationAlertId: string | null
        ) => BillingAlertConfiguration | null
        destinationTypeExists: (
            destinationAlert: BillingAlertConfiguration | null,
            selectedDestinationKey: BillingAlertDestinationKey
        ) => boolean
        slackExecutionTeamMismatch: (
            destinationAlert: BillingAlertConfiguration | null,
            selectedDestinationKey: BillingAlertDestinationKey,
            currentTeamId: number | null
        ) => boolean
        filteredAlerts: (
            alerts: BillingAlertConfiguration[],
            filters: BillingAlertListFilters
        ) => BillingAlertConfiguration[]
        hiddenAlertCount: (alerts: BillingAlertConfiguration[], filteredAlerts: BillingAlertConfiguration[]) => number
        canSubmit: (
            form: BillingAlertForm,
            selectedDestinationKey: BillingAlertDestinationKey,
            slackIntegrationId: number | null,
            slackChannel: string | null,
            webhookUrl: string
        ) => boolean
        canCreateDestination: (
            destinationAlertId: string | null,
            selectedDestinationKey: BillingAlertDestinationKey,
            slackIntegrationId: number | null,
            slackChannel: string | null,
            webhookUrl: string,
            destinationTypeExists: boolean,
            slackExecutionTeamMismatch: boolean
        ) => boolean
    }
}

export type billingAlertsLogicType = MakeLogicType<
    billingAlertsLogicValues,
    billingAlertsLogicActions,
    Record<string, any>,
    billingAlertsLogicMeta
>

export const billingAlertsLogic = kea<billingAlertsLogicType>([
    path(['products', 'billing_alerts', 'frontend', 'billingAlertsLogic']),

    connect(() => ({
        values: [billingLogic, ['currentOrganization', 'canAccessBilling'], teamLogic, ['currentTeamId']],
    })),

    actions({
        setCreationView: (view: BillingAlertCreationView) => ({ view }),
        setWizardStep: (step: BillingAlertWizardStep) => ({ step }),
        selectDestination: (destinationKey: BillingAlertDestinationKey) => ({ destinationKey }),
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
        setEventsFailed: (alertId: string) => ({ alertId }),
        setAlertsLoadFailed: (failed: boolean) => ({ failed }),
        openDestinationPanel: (alertId: string) => ({ alertId }),
        setDestinationAlertId: (alertId: string | null) => ({ alertId }),
        setSlackIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setSlackChannel: (slackChannel: string | null) => ({ slackChannel }),
        setWebhookUrl: (webhookUrl: string) => ({ webhookUrl }),
        createDestination: true,
        deleteDestination: (alert: BillingAlertConfiguration, destination: BillingAlertDestination) => ({
            alert,
            destination,
        }),
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
                selectDestination: () => BillingAlertWizardStep.Trigger,
                selectTrigger: () => BillingAlertWizardStep.Configure,
                resetCreation: () => BillingAlertWizardStep.Destination,
            },
        ],
        selectedDestinationKey: [
            'slack' as BillingAlertDestinationKey,
            {
                selectDestination: (_, { destinationKey }) => destinationKey,
                setSelectedDestinationKey: (_, { destinationKey }) => destinationKey,
                openDestinationPanel: () => 'slack' as BillingAlertDestinationKey,
                setDestinationAlertId: (state, { alertId }) =>
                    alertId === null ? ('slack' as BillingAlertDestinationKey) : state,
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
        eventsLoadFailedIds: [
            new Set<string>(),
            {
                setEvents: (state, { alertId }) => new Set([...state].filter((id) => id !== alertId)),
                setEventsFailed: (state, { alertId }) => new Set([...state, alertId]),
            },
        ],
        alertsLoadFailed: [
            false,
            {
                setAlertsLoadFailed: (_, { failed }) => failed,
            },
        ],
        destinationAlertId: [
            null as string | null,
            {
                openDestinationPanel: (_, { alertId }) => alertId,
                setDestinationAlertId: (_, { alertId }) => alertId,
                resetCreation: () => null,
            },
        ],
        slackIntegrationId: [
            null as number | null,
            {
                setSlackIntegrationId: (_, { integrationId }) => integrationId,
                openDestinationPanel: () => null,
                setDestinationAlertId: (state, { alertId }) => (alertId === null ? null : state),
                resetCreation: () => null,
            },
        ],
        slackChannel: [
            null as string | null,
            {
                setSlackChannel: (_, { slackChannel }) => slackChannel,
                setSlackIntegrationId: () => null,
                openDestinationPanel: () => null,
                setDestinationAlertId: (state, { alertId }) => (alertId === null ? null : state),
                resetCreation: () => null,
            },
        ],
        webhookUrl: [
            '',
            {
                setWebhookUrl: (_, { webhookUrl }) => webhookUrl,
                openDestinationPanel: () => '',
                setDestinationAlertId: (state, { alertId }) => (alertId === null ? '' : state),
                resetCreation: () => '',
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

    loaders(({ values, actions }) => ({
        alerts: [
            [] as BillingAlertConfiguration[],
            {
                loadAlerts: async () => {
                    const organizationId = values.currentOrganization?.id
                    if (!organizationId || !values.canAccessBilling) {
                        return []
                    }
                    actions.setAlertsLoadFailed(false)
                    try {
                        const response = await billingAlertsList(organizationId, { limit: 500 })
                        return response.results as BillingAlertConfiguration[]
                    } catch (error) {
                        actions.setAlertsLoadFailed(true)
                        lemonToast.error(apiMessage(error))
                        return values.alerts
                    }
                },
            },
        ],
    })),

    selectors({
        destinationAlert: [
            (s) => [s.alerts, s.destinationAlertId],
            (
                alerts: BillingAlertConfiguration[],
                destinationAlertId: string | null
            ): BillingAlertConfiguration | null => alerts.find((alert) => alert.id === destinationAlertId) ?? null,
        ],
        destinationTypeExists: [
            (s) => [s.destinationAlert, s.selectedDestinationKey],
            (alert: BillingAlertConfiguration | null, destinationType: BillingAlertDestinationKey): boolean =>
                !!alert?.destination_types.includes(destinationType),
        ],
        slackExecutionTeamMismatch: [
            (s) => [s.destinationAlert, s.selectedDestinationKey, s.currentTeamId],
            (
                alert: BillingAlertConfiguration | null,
                destinationType: BillingAlertDestinationKey,
                currentTeamId: number
            ): boolean => destinationType === 'slack' && !!alert && alert.execution_team_id !== currentTeamId,
        ],
        filteredAlerts: [
            (s) => [s.alerts, s.filters],
            (alerts: BillingAlertConfiguration[], filters: BillingAlertListFilters): BillingAlertConfiguration[] => {
                const search = filters.search.trim().toLowerCase()
                return alerts.filter((alert) => {
                    if (isBillingAlertHiddenByPausedFilter(alert, filters.showPaused)) {
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
            (s) => [s.form, s.selectedDestinationKey, s.slackIntegrationId, s.slackChannel, s.webhookUrl],
            (
                form: BillingAlertForm,
                selectedDestinationKey: BillingAlertDestinationKey,
                slackIntegrationId: number | null,
                slackChannel: string | null,
                webhookUrl: string
            ): boolean => {
                const hasThreshold =
                    form.threshold_type === 'relative_increase'
                        ? form.threshold_percentage > 0
                        : form.threshold_value !== undefined
                const hasDestination = !!destinationPayload({
                    destinationKey: selectedDestinationKey,
                    slackIntegrationId,
                    slackChannel,
                    webhookUrl,
                })
                return !!form.name.trim() && hasThreshold && hasDestination && formValuesInRange(form)
            },
        ],
        canCreateDestination: [
            (s) => [
                s.destinationAlertId,
                s.selectedDestinationKey,
                s.slackIntegrationId,
                s.slackChannel,
                s.webhookUrl,
                s.destinationTypeExists,
                s.slackExecutionTeamMismatch,
            ],
            (
                destinationAlertId: string | null,
                selectedDestinationKey: BillingAlertDestinationKey,
                slackIntegrationId: number | null,
                slackChannel: string | null,
                webhookUrl: string,
                destinationTypeExists: boolean,
                slackExecutionTeamMismatch: boolean
            ): boolean =>
                !!destinationAlertId &&
                !destinationTypeExists &&
                !slackExecutionTeamMismatch &&
                !!destinationPayload({
                    destinationKey: selectedDestinationKey,
                    slackIntegrationId,
                    slackChannel,
                    webhookUrl,
                }),
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
                const payload = destinationPayload({
                    destinationKey: values.selectedDestinationKey,
                    slackIntegrationId: values.slackIntegrationId,
                    slackChannel: values.slackChannel,
                    webhookUrl: values.webhookUrl,
                })
                if (payload) {
                    try {
                        await billingAlertsDestinationsCreate(organizationId, created.id, payload)
                    } catch (destinationError) {
                        await billingAlertsDestroy(organizationId, created.id).catch(() => null)
                        throw destinationError
                    }
                }
                lemonToast.success('Billing alert created.')
                actions.resetCreation()
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
                actions.loadAlerts()
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
                actions.setEventsFailed(alertId)
                lemonToast.error(apiMessage(error))
            }
        },
        createDestination: async () => {
            const organizationId = values.currentOrganization?.id
            const payload = destinationPayload({
                destinationKey: values.selectedDestinationKey,
                slackIntegrationId: values.slackIntegrationId,
                slackChannel: values.slackChannel,
                webhookUrl: values.webhookUrl,
            })
            if (!organizationId || !values.destinationAlertId || !payload || values.destinationSaving) {
                return
            }

            actions.setDestinationSaving(true)
            try {
                await billingAlertsDestinationsCreate(organizationId, values.destinationAlertId, payload)
                lemonToast.success('Destination added.')
                actions.setDestinationAlertId(null)
                actions.setSlackIntegrationId(null)
                actions.setSlackChannel(null)
                actions.setWebhookUrl('')
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setDestinationSaving(false)
            }
        },
        deleteDestination: async ({ alert, destination }) => {
            const organizationId = values.currentOrganization?.id
            if (!organizationId || values.updatingAlertIds.has(alert.id)) {
                return
            }

            actions.setUpdatingAlertId(alert.id, true)
            try {
                await billingAlertsDestinationsDeleteCreate(organizationId, alert.id, {
                    hog_function_ids: [...destination.hog_function_ids],
                })
                lemonToast.success('Destination removed.')
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(apiMessage(error))
            } finally {
                actions.setUpdatingAlertId(alert.id, false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAlerts()
    }),
])
