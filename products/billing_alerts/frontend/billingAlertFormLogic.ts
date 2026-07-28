import { MakeLogicType, afterMount, connect, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'

import type { OrganizationType } from '~/types'

import { billingAlertNotificationLogic } from './billingAlertNotificationLogic'
import type { PendingBillingAlertDestination } from './billingAlertNotificationLogic'
import { billingAlertsLogic } from './billingAlertsLogic'
import { billingAlertRequestError } from './billingAlertUtils'
import { billingAlertsCreate, billingAlertsPartialUpdate } from './generated/api'
import type {
    BillingAlertConfigurationApi,
    PatchedBillingAlertConfigurationApi,
    ThresholdTypeEnumApi,
} from './generated/api.schemas'

export interface BillingAlertFormValues {
    name: string
    description: string
    enabled: boolean
    thresholdType: ThresholdTypeEnumApi
    thresholdPercentage: number
    thresholdValue: number
    minimumValue: number
    baselineWindowDays: number
    evaluationDelayHours: number
    cooldownHours: number
}

export interface BillingAlertFormLogicProps {
    alert: BillingAlertConfigurationApi | null
}

const API_FIELD_TO_FORM_FIELD: Record<string, keyof BillingAlertFormValues> = {
    name: 'name',
    description: 'description',
    enabled: 'enabled',
    threshold_type: 'thresholdType',
    threshold_percentage: 'thresholdPercentage',
    threshold_value: 'thresholdValue',
    minimum_value: 'minimumValue',
    baseline_window_days: 'baselineWindowDays',
    evaluation_delay_hours: 'evaluationDelayHours',
    cooldown_hours: 'cooldownHours',
}

function firstErrorMessage(value: unknown): string | undefined {
    if (typeof value === 'string') {
        return value
    }
    if (Array.isArray(value)) {
        return value.map(firstErrorMessage).find(Boolean)
    }
    if (value && typeof value === 'object') {
        return Object.values(value).map(firstErrorMessage).find(Boolean)
    }
    return undefined
}

export function formErrorsFromApiError(error: unknown): Record<string, string> {
    if (!(error instanceof ApiError) || !error.data || typeof error.data !== 'object' || Array.isArray(error.data)) {
        return {}
    }
    return Object.fromEntries(
        Object.entries(error.data)
            .map(([field, value]) => {
                const formField = API_FIELD_TO_FORM_FIELD[field]
                const message = firstErrorMessage(value)
                return formField && message ? [formField, message] : null
            })
            .filter((entry): entry is [string, string] => entry !== null)
    )
}

export function billingAlertSaveErrorMessage(error: unknown): string {
    if (error instanceof ApiError && !error.detail) {
        const fieldMessage = firstErrorMessage(error.data)
        if (fieldMessage) {
            return fieldMessage
        }
    }
    return billingAlertRequestError(error, 'Failed to save billing alert.')
}

function numberValue(value: string | null | undefined, fallback: number): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : fallback
}

// Shared with the editor's advanced-options badge, which counts fields diverging from these.
export const ADVANCED_OPTION_DEFAULTS = {
    minimumValue: 0,
    evaluationDelayHours: 6,
    cooldownHours: 24,
} as const

function formDefaults(alert: BillingAlertConfigurationApi | null): BillingAlertFormValues {
    return {
        name: alert?.name ?? '',
        description: alert?.description ?? '',
        enabled: alert?.enabled ?? true,
        thresholdType: alert?.threshold_type ?? 'relative_increase',
        thresholdPercentage: numberValue(alert?.threshold_percentage, 50),
        thresholdValue: numberValue(alert?.threshold_value, 100),
        minimumValue: numberValue(alert?.minimum_value, ADVANCED_OPTION_DEFAULTS.minimumValue),
        baselineWindowDays: alert?.baseline_window_days ?? 7,
        evaluationDelayHours: alert?.evaluation_delay_hours ?? ADVANCED_OPTION_DEFAULTS.evaluationDelayHours,
        cooldownHours: alert?.cooldown_hours ?? ADVANCED_OPTION_DEFAULTS.cooldownHours,
    }
}

export function billingAlertWritePayload(
    form: BillingAlertFormValues,
    pending: PendingBillingAlertDestination[]
): PatchedBillingAlertConfigurationApi {
    return {
        name: form.name.trim(),
        description: form.description.trim(),
        enabled: form.enabled,
        threshold_type: form.thresholdType,
        threshold_percentage: form.thresholdType === 'relative_increase' ? String(form.thresholdPercentage) : null,
        threshold_value: form.thresholdType === 'relative_increase' ? null : String(form.thresholdValue),
        minimum_value: String(form.minimumValue),
        baseline_window_days: form.baselineWindowDays,
        evaluation_delay_hours: form.evaluationDelayHours,
        cooldown_hours: form.cooldownHours,
        ...(pending.length > 0 ? { destination_changes: { create: pending.map(({ payload }) => payload) } } : {}),
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertFormLogicValues {
    pendingDestinations: PendingBillingAlertDestination[] // billingAlertNotificationLogic
    currentOrganization: OrganizationType | null // billingLogic
    alertForm: BillingAlertFormValues
    alertFormAllErrors: Record<string, any>
    alertFormChanged: boolean
    alertFormErrors: DeepPartialMap<BillingAlertFormValues, ValidationErrorType>
    alertFormHasErrors: boolean
    alertFormManualErrors: Record<string, any>
    alertFormTouched: boolean
    alertFormTouches: Record<string, boolean>
    alertFormValidationErrors: DeepPartialMap<BillingAlertFormValues, ValidationErrorType>
    isAlertFormSubmitting: boolean
    isAlertFormValid: boolean
    showAlertFormErrors: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertFormLogicActions {
    clearCreatedDestinations: (keys: string[]) => {
        keys: string[]
    } // billingAlertNotificationLogic
    closeEditor: () => {
        value: true
    } // billingAlertsLogic
    loadAlerts: () => void // billingAlertsLogic
    resetAlertForm: (values?: BillingAlertFormValues) => {
        values?: BillingAlertFormValues
    }
    setAlertFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setAlertFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setAlertFormValues: (values: DeepPartial<BillingAlertFormValues>) => {
        values: DeepPartial<BillingAlertFormValues>
    }
    submitAlertForm: () => {
        value: boolean
    }
    submitAlertFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitAlertFormRequest: (alertForm: BillingAlertFormValues) => {
        alertForm: BillingAlertFormValues
    }
    submitAlertFormSuccess: (alertForm: BillingAlertFormValues) => {
        alertForm: BillingAlertFormValues
    }
    touchAlertFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingAlertFormLogicMeta {
    key: string
}

export type billingAlertFormLogicType = MakeLogicType<
    billingAlertFormLogicValues,
    billingAlertFormLogicActions,
    BillingAlertFormLogicProps,
    billingAlertFormLogicMeta
>

export const billingAlertFormLogic = kea<billingAlertFormLogicType>([
    path(['products', 'billingAlerts', 'frontend', 'billingAlertFormLogic']),
    props({} as BillingAlertFormLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),
    // The notification logic shares this logic's key, so both connect to the same instance
    // BindLogic mounts in BillingAlertEditor.
    connect((props: BillingAlertFormLogicProps) => ({
        values: [billingLogic, ['currentOrganization'], billingAlertNotificationLogic(props), ['pendingDestinations']],
        actions: [
            billingAlertsLogic,
            ['loadAlerts', 'closeEditor'],
            billingAlertNotificationLogic(props),
            ['clearCreatedDestinations'],
        ],
    })),
    afterMount(({ actions, props }) => {
        actions.resetAlertForm(formDefaults(props.alert))
    }),
    forms(({ props, values, actions }) => ({
        alertForm: {
            defaults: formDefaults(props.alert),
            errors: (form) => ({
                name: form.name.trim() ? undefined : 'Name is required.',
                thresholdPercentage:
                    form.thresholdType === 'relative_increase' && form.thresholdPercentage <= 0
                        ? 'Enter a percentage greater than 0.'
                        : undefined,
                thresholdValue:
                    form.thresholdType !== 'relative_increase' && form.thresholdValue < 0
                        ? 'Enter a value of 0 or more.'
                        : undefined,
                minimumValue: form.minimumValue < 0 ? 'Enter a value of 0 or more.' : undefined,
                baselineWindowDays:
                    form.baselineWindowDays < 1 || form.baselineWindowDays > 90
                        ? 'Use a baseline between 1 and 90 days.'
                        : undefined,
                evaluationDelayHours:
                    form.evaluationDelayHours < 0 || form.evaluationDelayHours > 72
                        ? 'Use a delay between 0 and 72 hours.'
                        : undefined,
                cooldownHours:
                    form.cooldownHours < 0 || form.cooldownHours > 720
                        ? 'Use a cooldown between 0 and 720 hours.'
                        : undefined,
            }),
            submit: async (form) => {
                const organizationId = values.currentOrganization?.id
                if (!organizationId) {
                    throw new Error('No organization selected.')
                }

                const pending = values.pendingDestinations
                if (!props.alert && pending.length === 0) {
                    lemonToast.error('Add at least one notification destination.')
                    throw new Error('A notification destination is required.')
                }

                try {
                    const pendingKeys = pending.map(({ key }) => key)
                    const formPayload = billingAlertWritePayload(form, pending)
                    if (props.alert) {
                        await billingAlertsPartialUpdate(organizationId, props.alert.id, formPayload)
                    } else {
                        await billingAlertsCreate(
                            organizationId,
                            formPayload as Parameters<typeof billingAlertsCreate>[1]
                        )
                    }
                    actions.clearCreatedDestinations(pendingKeys)

                    lemonToast.success(props.alert ? 'Billing alert updated.' : 'Billing alert created.')
                    actions.loadAlerts()
                    actions.closeEditor()
                    return form
                } catch (error) {
                    const fieldErrors = formErrorsFromApiError(error)
                    if (Object.keys(fieldErrors).length > 0) {
                        actions.setAlertFormManualErrors(fieldErrors)
                    }
                    const message = billingAlertSaveErrorMessage(error)
                    lemonToast.error(message)
                    throw error
                }
            },
        },
    })),
])
