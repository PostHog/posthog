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

export interface NewPipelineFormValues {
    name: string
    target_event: string
    horizon_days: number
    training_lookback_days: number
    training_population: AnyPropertyFilter[]
    inference_population: AnyPropertyFilter[]
}

const DEFAULTS: NewPipelineFormValues = {
    name: '',
    target_event: '',
    horizon_days: 30,
    training_lookback_days: 180,
    training_population: [],
    inference_population: [],
}

const VALIDATE_DEBOUNCE_MS = 500

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
                    const {
                        target_event,
                        horizon_days,
                        training_lookback_days,
                        training_population,
                        inference_population,
                    } = values.newPipeline
                    const trimmed = target_event.trim()
                    if (!teamId || !trimmed) {
                        return null
                    }
                    const body: ValidatePipelineRequestApi = {
                        target_event: trimmed,
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
            errors: ({ name, target_event, horizon_days, training_lookback_days }: NewPipelineFormValues) => ({
                name: !name.trim() ? 'Give the pipeline a name' : undefined,
                target_event: !target_event.trim() ? 'Pick a target event to predict' : undefined,
                horizon_days:
                    !horizon_days || horizon_days < 1 ? 'Prediction horizon must be at least 1 day' : undefined,
                training_lookback_days:
                    !training_lookback_days || training_lookback_days < 7
                        ? 'Training lookback must be at least 7 days'
                        : training_lookback_days > 730
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
                const body: AutoresearchPipelineCreateApi = {
                    name: payload.name.trim(),
                    target_event: payload.target_event.trim(),
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
                next.target_event !== prev.target_event ||
                next.horizon_days !== prev.horizon_days ||
                next.training_lookback_days !== prev.training_lookback_days ||
                trainingChanged ||
                inferenceChanged
            ) {
                actions.runValidate()
            }
        },
    })),
])
