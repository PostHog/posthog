import { actions, connect, kea, path } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter } from '~/types'

import type { autoresearchNewLogicType } from './autoresearchNewLogicType'
import { autoresearchCreate, autoresearchValidateCreate } from './generated/api'
import {
    AutoresearchPipelineCreateApi,
    ValidatePipelineRequestApi,
    ValidatePipelineResponseApi,
} from './generated/api.schemas'

export type TargetType = 'event' | 'action'

export interface NewPipelineFormValues {
    name: string
    target_type: TargetType
    // For event targets this is the event name; for action targets it's the action's
    // display name (kept for the UI label and output-person-property derivation).
    target_event: string
    target_action_id: number | null
    horizon_days: number
    training_lookback_days: number
    training_population: AnyPropertyFilter[]
    inference_population: AnyPropertyFilter[]
}

const DEFAULTS: NewPipelineFormValues = {
    name: '',
    target_type: 'event',
    target_event: '',
    target_action_id: null,
    horizon_days: 30,
    training_lookback_days: 180,
    training_population: [],
    inference_population: [],
}

const VALIDATE_DEBOUNCE_MS = 500

/** True once the chosen target (event name, or action id) is complete enough to validate/create. */
function hasTarget(values: NewPipelineFormValues): boolean {
    return values.target_type === 'action' ? values.target_action_id != null : !!values.target_event.trim()
}

/** Build the target request fields shared by validate + create. */
function targetRequestFields(values: NewPipelineFormValues): {
    target_event: string
    target_definition: Record<string, unknown>
} {
    if (values.target_type === 'action' && values.target_action_id != null) {
        return {
            target_event: values.target_event.trim(),
            target_definition: { type: 'action', action_id: values.target_action_id },
        }
    }
    return { target_event: values.target_event.trim(), target_definition: {} }
}

export const autoresearchNewLogic = kea<autoresearchNewLogicType>([
    path(['products', 'autoresearch', 'autoresearchNewLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        resetValidation: true,
    }),
    loaders(({ values }) => ({
        validation: [
            null as ValidatePipelineResponseApi | null,
            {
                resetValidation: () => null,
                runValidate: async (_payload, breakpoint) => {
                    await breakpoint(VALIDATE_DEBOUNCE_MS)
                    const teamId = values.currentTeamId
                    const { horizon_days, training_lookback_days, training_population, inference_population } =
                        values.newPipeline
                    if (!teamId || !hasTarget(values.newPipeline)) {
                        return null
                    }
                    const { target_event, target_definition } = targetRequestFields(values.newPipeline)
                    const body: ValidatePipelineRequestApi = {
                        target_event,
                        target_definition: target_definition as ValidatePipelineRequestApi['target_definition'],
                        horizon_days,
                        training_lookback_days,
                        training_population: training_population.length > 0 ? { properties: training_population } : {},
                        inference_population:
                            inference_population.length > 0 ? { properties: inference_population } : {},
                    }
                    const response = await autoresearchValidateCreate(String(teamId), body)
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        newPipeline: {
            defaults: DEFAULTS,
            errors: (formValues: NewPipelineFormValues) => ({
                name: !formValues.name.trim() ? 'Give the pipeline a name' : undefined,
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
                        : undefined,
                training_lookback_days:
                    !formValues.training_lookback_days || formValues.training_lookback_days < 7
                        ? 'Training lookback must be at least 7 days'
                        : formValues.training_lookback_days > 730
                          ? 'Training lookback must be 730 days or fewer'
                          : undefined,
            }),
            submit: async (payload: NewPipelineFormValues) => {
                if (!values.currentTeamId) {
                    lemonToast.error('No active team — cannot create pipeline')
                    return
                }
                if (values.validation && !values.validation.can_proceed) {
                    lemonToast.error('Validation flagged blocking errors — fix them before creating.')
                    return
                }
                const { target_event, target_definition } = targetRequestFields(payload)
                const body: AutoresearchPipelineCreateApi = {
                    name: payload.name.trim(),
                    target_event,
                    target_definition: target_definition as AutoresearchPipelineCreateApi['target_definition'],
                    horizon_days: payload.horizon_days,
                    training_lookback_days: payload.training_lookback_days,
                    training_population:
                        payload.training_population.length > 0
                            ? ({
                                  properties: payload.training_population,
                              } as unknown as AutoresearchPipelineCreateApi['training_population'])
                            : ({} as unknown as AutoresearchPipelineCreateApi['training_population']),
                    inference_population:
                        payload.inference_population.length > 0
                            ? ({
                                  properties: payload.inference_population,
                              } as unknown as AutoresearchPipelineCreateApi['inference_population'])
                            : ({} as unknown as AutoresearchPipelineCreateApi['inference_population']),
                }
                try {
                    const created = await autoresearchCreate(String(values.currentTeamId), body)
                    lemonToast.success(`Created "${created.name}"`)
                    actions.resetNewPipeline()
                    router.actions.push(urls.autoresearch())
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ??
                            error?.data?.detail ??
                            'Failed to create pipeline. Check the form and try again.'
                    )
                    throw error
                }
            },
        },
    })),
    subscriptions(({ actions }) => ({
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
                trainingChanged ||
                inferenceChanged
            ) {
                actions.runValidate(null)
            }
        },
    })),
])
