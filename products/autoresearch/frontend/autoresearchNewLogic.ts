import { MakeLogicType, actions, afterMount, connect, isBreakpoint, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter } from '~/types'

import type { FeatureFlagsSet } from '../../../frontend/src/lib/logic/featureFlagLogic'
import {
    autoresearchCreate,
    autoresearchResolveTemplateCreate,
    autoresearchTemplatesList,
    autoresearchValidateCreate,
} from './generated/api'
import {
    AutoresearchPipelineCreateApi,
    ResolvedTemplateApi,
    TemplateInfoApi,
    TemplateKeyEnumApi,
    ValidatePipelineRequestApi,
    ValidatePipelineResponseApi,
} from './generated/api.schemas'

type TargetType = 'event' | 'action'

/** A semantic population spec (`{"kind": ...}`) from resolve-template. */
type PopulationKind = Record<string, unknown>

interface NewPipelineFormValues {
    name: string
    target_type: TargetType
    // For event targets this is the event name; for action targets it's the action's
    // display name (kept for the UI label and output-person-property derivation).
    target_event: string
    target_action_id: number | null
    horizon_days: number
    training_lookback_days: number
    // The people the model scores. Training uses them too unless separate_training_population is on.
    inference_population: AnyPropertyFilter[]
    separate_training_population: boolean
    training_population: AnyPropertyFilter[]
    iteration_budget: number
    // Null for a custom definition.
    template_key: TemplateKeyEnumApi | null
    inference_population_kind: PopulationKind | null
    training_population_kind: PopulationKind | null
    output_person_property: string
}

const DEFAULTS: NewPipelineFormValues = {
    name: '',
    target_type: 'event',
    target_event: '',
    target_action_id: null,
    horizon_days: 30,
    training_lookback_days: 180,
    inference_population: [],
    separate_training_population: false,
    training_population: [],
    iteration_budget: 50,
    template_key: null,
    inference_population_kind: null,
    training_population_kind: null,
    output_person_property: '',
}

export const HORIZON_PRESETS = [7, 14, 30, 90]

const VALIDATE_DEBOUNCE_MS = 500
const RESOLVE_DEBOUNCE_MS = 300

/** True once the chosen target (event name, or action id) is complete enough to validate/create. */
export function hasTarget(values: NewPipelineFormValues): boolean {
    return values.target_type === 'action' ? values.target_action_id != null : !!values.target_event.trim()
}

/** Build the target request fields shared by validate + create. */
function targetRequestFields(values: NewPipelineFormValues): {
    target_event: string
    target_definition: Record<string, unknown>
} {
    if (values.target_type === 'action' && values.target_action_id != null) {
        // The API derives target_event from the action. The display name can exceed its 255-character limit.
        return {
            target_event: '',
            target_definition: { type: 'action', action_id: values.target_action_id },
        }
    }
    return { target_event: values.target_event.trim(), target_definition: {} }
}

function populationBody(kind: PopulationKind | null, filters: AnyPropertyFilter[]): Record<string, unknown> {
    return { ...kind, ...(filters.length > 0 ? { properties: filters } : {}) }
}

/** Build the population request fields shared by validate + create. */
function populationRequestFields(values: NewPipelineFormValues): {
    training_population: Record<string, unknown>
    inference_population: Record<string, unknown>
} {
    const inference_population = populationBody(values.inference_population_kind, values.inference_population)
    const training_population = values.separate_training_population
        ? populationBody(values.training_population_kind, values.training_population)
        : inference_population
    return { training_population, inference_population }
}

function kindPhrase(kind: PopulationKind | null): string | null {
    const days = kind?.days ?? kind?.active_within_days
    switch (kind?.kind) {
        case 'performed_event_within_days':
            return `users who did ${kind.event ?? 'any event'} in the last ${days} days`
        case 'person_first_seen_within_days':
            return `users first seen in the last ${days} days`
        case 'active_not_performed_target':
            return `users active in the last ${days} days who haven't done it yet`
        case 'ever_performed_event':
            return `users who have done ${kind.event}`
        case 'ever_performed_target':
            return 'users who have done it before'
        default:
            return null
    }
}

/** A short noun phrase for a population, e.g. "users first seen in the last 14 days matching 2 filters". */
export function populationSummary(kind: PopulationKind | null, filters: AnyPropertyFilter[]): string {
    const base = kindPhrase(kind) ?? 'all identified users'
    if (filters.length === 0) {
        return base
    }
    return `${base} matching ${filters.length} ${filters.length === 1 ? 'filter' : 'filters'}`
}

/** The form values a resolve-template response sets. Fields the user edited keep their value. */
function valuesFromResolvedTemplate(
    resolved: ResolvedTemplateApi,
    previous: ResolvedTemplateApi | null,
    current: NewPipelineFormValues
): Partial<NewPipelineFormValues> {
    const nameFollowsTemplate = !current.name.trim() || current.name === previous?.suggested_name
    const lookbackFollowsTemplate = !previous || current.training_lookback_days === previous.training_lookback_days
    return {
        template_key: resolved.template_key,
        target_type: 'event',
        target_event: resolved.target_event,
        target_action_id: null,
        horizon_days: resolved.horizon_days,
        inference_population_kind: resolved.inference_population as PopulationKind,
        training_population_kind: resolved.training_population as PopulationKind,
        output_person_property: resolved.output_person_property,
        ...(nameFollowsTemplate ? { name: resolved.suggested_name } : {}),
        ...(lookbackFollowsTemplate ? { training_lookback_days: resolved.training_lookback_days } : {}),
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface autoresearchNewLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentTeamId: number | null // teamLogic
    advancedOpen: boolean
    isNewPipelineSubmitting: boolean
    isNewPipelineValid: boolean
    newPipeline: NewPipelineFormValues
    newPipelineAllErrors: Record<string, any>
    newPipelineChanged: boolean
    newPipelineErrors: DeepPartialMap<NewPipelineFormValues, ValidationErrorType>
    newPipelineHasErrors: boolean
    newPipelineManualErrors: Record<string, any>
    newPipelineTouched: boolean
    newPipelineTouches: Record<string, boolean>
    newPipelineValidationErrors: DeepPartialMap<NewPipelineFormValues, ValidationErrorType>
    resolvedTemplate: ResolvedTemplateApi | null
    resolvedTemplateLoading: boolean
    showNewPipelineErrors: boolean
    templates: TemplateInfoApi[]
    templatesLoading: boolean
    validation: ValidatePipelineResponseApi | null
    validationFailed: boolean
    validationLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface autoresearchNewLogicActions {
    clearValidation: () => {
        value: boolean
    }
    loadTemplates: () => any
    loadTemplatesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTemplatesSuccess: (
        templates: TemplateInfoApi[],
        payload?: any
    ) => {
        templates: TemplateInfoApi[]
        payload?: any
    }
    resetNewPipeline: (values?: NewPipelineFormValues) => {
        values?: NewPipelineFormValues
    }
    resolveTemplate: (
        templateKey: TemplateKeyEnumApi,
        targetEvent?: string,
        horizonDays?: number
    ) => {
        horizonDays: number | undefined
        targetEvent: string | undefined
        templateKey: TemplateKeyEnumApi
    }
    resolveTemplateFailure: () => {
        value: true
    }
    resolveTemplateSuccess: (resolved: ResolvedTemplateApi) => {
        resolved: ResolvedTemplateApi
    }
    runValidate: (_payload: any) => any
    runValidateFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    runValidateSuccess: (
        validation: ValidatePipelineResponseApi | null,
        payload?: any
    ) => {
        validation: ValidatePipelineResponseApi | null
        payload?: any
    }
    selectTemplate: (templateKey: TemplateKeyEnumApi | null) => {
        templateKey: TemplateKeyEnumApi | null
    }
    setAdvancedOpen: (open: boolean) => {
        open: boolean
    }
    setNewPipelineManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setNewPipelineValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setNewPipelineValues: (values: DeepPartial<NewPipelineFormValues>) => {
        values: DeepPartial<NewPipelineFormValues>
    }
    submitNewPipeline: () => {
        value: boolean
    }
    submitNewPipelineFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitNewPipelineRequest: (newPipeline: NewPipelineFormValues) => {
        newPipeline: NewPipelineFormValues
    }
    submitNewPipelineSuccess: (newPipeline: NewPipelineFormValues) => {
        newPipeline: NewPipelineFormValues
    }
    touchNewPipelineField: (key: string) => {
        key: string
    }
}

export type autoresearchNewLogicType = MakeLogicType<autoresearchNewLogicValues, autoresearchNewLogicActions>

export const autoresearchNewLogic = kea<autoresearchNewLogicType>([
    path(['products', 'autoresearch', 'autoresearchNewLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        clearValidation: () => ({ value: true }),
        selectTemplate: (templateKey: TemplateKeyEnumApi | null) => ({ templateKey }),
        resolveTemplate: (templateKey: TemplateKeyEnumApi, targetEvent?: string, horizonDays?: number) => ({
            templateKey,
            targetEvent,
            horizonDays,
        }),
        resolveTemplateSuccess: (resolved: ResolvedTemplateApi) => ({ resolved }),
        resolveTemplateFailure: true,
        setAdvancedOpen: (open: boolean) => ({ open }),
    }),
    loaders(({ values }) => ({
        templates: [
            [] as TemplateInfoApi[],
            {
                loadTemplates: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    return await autoresearchTemplatesList(String(values.currentTeamId))
                },
            },
        ],
        validation: [
            null as ValidatePipelineResponseApi | null,
            {
                runValidate: async (_payload, breakpoint) => {
                    await breakpoint(VALIDATE_DEBOUNCE_MS)
                    const teamId = values.currentTeamId
                    const { horizon_days, training_lookback_days } = values.newPipeline
                    const { horizon_days: horizonError, training_lookback_days: lookbackError } =
                        values.newPipelineValidationErrors
                    // A cleared number input holds NaN, which serializes to null and the API rejects.
                    if (!teamId || !hasTarget(values.newPipeline) || horizonError || lookbackError) {
                        return null
                    }
                    const { target_event, target_definition } = targetRequestFields(values.newPipeline)
                    const { training_population, inference_population } = populationRequestFields(values.newPipeline)
                    const body: ValidatePipelineRequestApi = {
                        target_event,
                        target_definition: target_definition as ValidatePipelineRequestApi['target_definition'],
                        horizon_days,
                        training_lookback_days,
                        training_population,
                        inference_population,
                    }
                    const response = await autoresearchValidateCreate(String(teamId), body)
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers({
        validation: [
            null as ValidatePipelineResponseApi | null,
            {
                clearValidation: () => null,
            },
        ],
        validationFailed: [
            false,
            {
                runValidate: () => false,
                runValidateSuccess: () => false,
                runValidateFailure: () => true,
                clearValidation: () => false,
            },
        ],
        resolvedTemplate: [
            null as ResolvedTemplateApi | null,
            {
                selectTemplate: () => null,
                resolveTemplateSuccess: (_, { resolved }) => resolved,
            },
        ],
        resolvedTemplateLoading: [
            false,
            {
                resolveTemplate: () => true,
                resolveTemplateSuccess: () => false,
                resolveTemplateFailure: () => false,
                selectTemplate: () => false,
            },
        ],
        advancedOpen: [
            false,
            {
                setAdvancedOpen: (_, { open }) => open,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        newPipeline: {
            defaults: DEFAULTS,
            errors: (formValues: NewPipelineFormValues) => ({
                name: !formValues.name.trim() ? 'Give the model a name' : undefined,
                target_event:
                    formValues.target_type === 'event' && !formValues.target_event.trim()
                        ? 'Pick a target event to predict'
                        : undefined,
                target_action_id:
                    formValues.target_type === 'action' && formValues.target_action_id == null
                        ? 'Pick a target action to predict'
                        : undefined,
                horizon_days:
                    !formValues.horizon_days || formValues.horizon_days < 1
                        ? 'Prediction horizon must be at least 1 day'
                        : formValues.horizon_days > 365
                          ? 'Prediction horizon must be 365 days or fewer'
                          : !Number.isInteger(formValues.horizon_days)
                            ? 'Prediction horizon must be a whole number of days'
                            : undefined,
                training_lookback_days:
                    !formValues.training_lookback_days || formValues.training_lookback_days < 7
                        ? 'Training lookback must be at least 7 days'
                        : formValues.training_lookback_days > 730
                          ? 'Training lookback must be 730 days or fewer'
                          : !Number.isInteger(formValues.training_lookback_days)
                            ? 'Training lookback must be a whole number of days'
                            : undefined,
                iteration_budget:
                    !formValues.iteration_budget || formValues.iteration_budget < 1
                        ? 'Experiment budget must be at least 1'
                        : formValues.iteration_budget > 500
                          ? 'Experiment budget must be 500 or fewer'
                          : !Number.isInteger(formValues.iteration_budget)
                            ? 'Experiment budget must be a whole number'
                            : undefined,
            }),
            submit: async (payload: NewPipelineFormValues) => {
                if (!values.currentTeamId) {
                    lemonToast.error('Select a project before creating a model')
                    return
                }
                if (values.validationFailed) {
                    lemonToast.error('Validation failed to run. Retry it, then create.')
                    return
                }
                if (values.validationLoading || !values.validation) {
                    // The form clears its validation on every change and re-runs it debounced, so a
                    // null or in-flight result means these values have never been checked.
                    lemonToast.error('Validation is still running. Wait for it to finish, then create.')
                    return
                }
                if (!values.validation.can_proceed) {
                    lemonToast.error('Validation found blocking errors. Fix them before creating.')
                    return
                }
                const { target_event, target_definition } = targetRequestFields(payload)
                const { training_population, inference_population } = populationRequestFields(payload)
                const body: AutoresearchPipelineCreateApi = {
                    name: payload.name.trim(),
                    target_event,
                    target_definition: target_definition as AutoresearchPipelineCreateApi['target_definition'],
                    horizon_days: payload.horizon_days,
                    training_lookback_days: payload.training_lookback_days,
                    training_population,
                    inference_population,
                    iteration_budget: payload.iteration_budget,
                    // Without a template the API derives the property from the target.
                    ...(payload.output_person_property
                        ? { output_person_property: payload.output_person_property }
                        : {}),
                }
                try {
                    const created = await autoresearchCreate(String(values.currentTeamId), body)
                    posthog.capture('autoresearch model created', {
                        pipeline_id: created.id,
                        target_type: payload.target_type,
                        template_key: payload.template_key,
                    })
                    lemonToast.success(`Created "${created.name}"`)
                    actions.resetNewPipeline()
                    router.actions.push(urls.autoresearch())
                } catch (error: any) {
                    posthog.capture('autoresearch model create failed', {
                        target_type: payload.target_type,
                        template_key: payload.template_key,
                    })
                    lemonToast.error(
                        error?.detail ??
                            error?.data?.detail ??
                            'Failed to create the model. Check the form and try again.'
                    )
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        runValidateSuccess: ({ validation }) => {
            if (validation) {
                posthog.capture('autoresearch model validated', {
                    can_proceed: validation.can_proceed,
                    target_type: values.newPipeline.target_type,
                    template_key: values.newPipeline.template_key,
                })
            }
        },
        selectTemplate: ({ templateKey }) => {
            if (templateKey === null) {
                posthog.capture('autoresearch model custom chosen')
                actions.setNewPipelineValues({
                    template_key: null,
                    inference_population_kind: null,
                    training_population_kind: null,
                    output_person_property: '',
                })
                return
            }
            posthog.capture('autoresearch model template selected', { template_key: templateKey })
            const template = values.templates.find((t) => t.key === templateKey)
            if (template?.requires_user_event) {
                // Templates take an event target. Keep the current event, and wait for one otherwise.
                const targetEvent = values.newPipeline.target_type === 'event' ? values.newPipeline.target_event : ''
                actions.setNewPipelineValues({
                    template_key: templateKey,
                    target_type: 'event',
                    target_event: targetEvent,
                    target_action_id: null,
                    horizon_days: template.default_horizon_days,
                    inference_population_kind: null,
                    training_population_kind: null,
                    output_person_property: '',
                })
                if (targetEvent.trim()) {
                    actions.resolveTemplate(templateKey, targetEvent.trim())
                }
                return
            }
            actions.setNewPipelineValues({ template_key: templateKey })
            actions.resolveTemplate(templateKey)
        },
        resolveTemplate: async ({ templateKey, targetEvent, horizonDays }, breakpoint) => {
            const teamId = values.currentTeamId
            if (!teamId) {
                actions.resolveTemplateFailure()
                return
            }
            try {
                await breakpoint(RESOLVE_DEBOUNCE_MS)
                const resolved = await autoresearchResolveTemplateCreate(String(teamId), {
                    template_key: templateKey,
                    ...(targetEvent ? { target_event: targetEvent } : {}),
                    ...(horizonDays ? { horizon_days: horizonDays } : {}),
                })
                breakpoint()
                if (values.newPipeline.template_key !== templateKey) {
                    actions.resolveTemplateFailure()
                    return
                }
                const previous = values.resolvedTemplate
                actions.resolveTemplateSuccess(resolved)
                // kea-forms types its setter with DeepPartial, which does not accept an opaque population spec.
                actions.setNewPipelineValues(
                    valuesFromResolvedTemplate(
                        resolved,
                        previous,
                        values.newPipeline
                    ) as DeepPartial<NewPipelineFormValues>
                )
            } catch (error: any) {
                if (isBreakpoint(error)) {
                    throw error
                }
                actions.resolveTemplateFailure()
                lemonToast.error(
                    error?.detail ?? error?.data?.detail ?? "Couldn't load this template. Try again, or use Custom."
                )
                // A template that never resolved has no populations, so fall back to a custom definition.
                if (!values.resolvedTemplate && values.newPipeline.template_key === templateKey) {
                    actions.setNewPipelineValues({ template_key: null })
                }
            }
        },
        setAdvancedOpen: ({ open }) => {
            if (open) {
                posthog.capture('autoresearch model advanced opened')
            }
        },
    })),
    urlToAction(({ values }) => ({
        [urls.autoresearchNew()]: () => {
            // With the flag off the scene shows NotFound, so there is no create flow to record.
            if (values.featureFlags[FEATURE_FLAGS.AUTORESEARCH]) {
                posthog.capture('autoresearch model create started')
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        newPipeline: (next: NewPipelineFormValues, prev: NewPipelineFormValues | undefined) => {
            if (!prev) {
                return
            }
            const trainingChanged =
                next.training_population !== prev.training_population &&
                JSON.stringify(next.training_population) !== JSON.stringify(prev.training_population)
            const inferenceChanged =
                next.inference_population !== prev.inference_population &&
                JSON.stringify(next.inference_population) !== JSON.stringify(prev.inference_population)
            if (
                next.target_type !== prev.target_type ||
                next.target_event !== prev.target_event ||
                next.target_action_id !== prev.target_action_id ||
                next.horizon_days !== prev.horizon_days ||
                next.training_lookback_days !== prev.training_lookback_days ||
                next.separate_training_population !== prev.separate_training_population ||
                next.inference_population_kind !== prev.inference_population_kind ||
                next.training_population_kind !== prev.training_population_kind ||
                trainingChanged ||
                inferenceChanged
            ) {
                actions.clearValidation()
                actions.runValidate(null)
            }
            // A template derives its populations and output property from the target and horizon,
            // so a change to either re-resolves it. A value the last resolution set needs no call.
            const resolved = values.resolvedTemplate
            const targetEvent = next.target_event.trim()
            if (
                next.template_key &&
                next.template_key === prev.template_key &&
                (next.target_event !== prev.target_event || next.horizon_days !== prev.horizon_days) &&
                targetEvent &&
                !values.newPipelineValidationErrors.horizon_days &&
                (targetEvent !== resolved?.target_event || next.horizon_days !== resolved?.horizon_days)
            ) {
                actions.resolveTemplate(next.template_key, targetEvent, next.horizon_days)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTemplates()
    }),
])
