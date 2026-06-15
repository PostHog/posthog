import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ApiConfig } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { urls } from '~/scenes/urls'
import { LLMPromptVersionSummary } from '~/types'

import {
    experimentsCreateFromPromptCreate,
    experimentsPromptTemplatesRetrieve,
} from '../../../experiments/frontend/generated/api'
import type {
    ExperimentsPromptTemplatesRetrieve200Item,
    TemplatesEnumApi,
} from '../../../experiments/frontend/generated/api.schemas'
import type { createPromptExperimentModalLogicType } from './createPromptExperimentModalLogicType'

export const MIN_VERSIONS = 2
export const MAX_VERSIONS = 10

export type VersionSlots = (number | null)[]

export const createPromptExperimentModalLogic = kea<createPromptExperimentModalLogicType>([
    path(['products', 'ai_observability', 'frontend', 'prompts', 'createPromptExperimentModalLogic']),

    actions({
        openModal: (promptName: string, promptVersions: LLMPromptVersionSummary[]) => ({
            promptName,
            promptVersions,
        }),
        closeModal: true,
        setVersionAt: (index: number, version: number | null) => ({ index, version }),
        addVersionSlot: true,
        removeVersionSlot: (index: number) => ({ index }),
        toggleTemplate: (template: TemplatesEnumApi) => ({ template }),
        setSelectedTemplates: (templates: TemplatesEnumApi[]) => ({ templates }),
        submitCreate: true,
        submitCreateSuccess: (experimentId: number) => ({ experimentId }),
        submitCreateFailure: (error: string) => ({ error }),
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        promptName: [
            null as string | null,
            {
                openModal: (_, { promptName }) => promptName,
                closeModal: () => null,
            },
        ],
        promptVersions: [
            [] as LLMPromptVersionSummary[],
            {
                openModal: (_, { promptVersions }) => promptVersions,
                closeModal: () => [],
            },
        ],
        versionSlots: [
            [null, null] as VersionSlots,
            {
                openModal: () => [null, null] as VersionSlots,
                closeModal: () => [null, null] as VersionSlots,
                addVersionSlot: (slots) => (slots.length >= MAX_VERSIONS ? slots : [...slots, null]),
                removeVersionSlot: (slots, { index }) =>
                    slots.length <= MIN_VERSIONS ? slots : slots.filter((_, i) => i !== index),
                setVersionAt: (slots, { index, version }) =>
                    slots.map((existing, i) => (i === index ? version : existing)),
            },
        ],
        selectedTemplates: [
            [] as TemplatesEnumApi[],
            {
                openModal: () => [] as TemplatesEnumApi[],
                closeModal: () => [] as TemplatesEnumApi[],
                toggleTemplate: (selected, { template }) =>
                    selected.includes(template) ? selected.filter((t) => t !== template) : [...selected, template],
                setSelectedTemplates: (_, { templates }) => templates,
            },
        ],
        isSubmitting: [
            false,
            {
                submitCreate: () => true,
                submitCreateSuccess: () => false,
                submitCreateFailure: () => false,
            },
        ],
    }),

    loaders({
        templates: [
            [] as ExperimentsPromptTemplatesRetrieve200Item[],
            {
                loadTemplates: async () => {
                    return await experimentsPromptTemplatesRetrieve(String(ApiConfig.getCurrentTeamId()))
                },
            },
        ],
    }),

    selectors({
        selectedVersions: [
            (s) => [s.versionSlots],
            (slots: VersionSlots): number[] => slots.filter((v): v is number => v !== null),
        ],
        canSubmit: [
            (s) => [s.selectedVersions, s.selectedTemplates, s.isSubmitting, s.promptName, s.versionSlots],
            (
                versions: number[],
                selectedTemplates: TemplatesEnumApi[],
                submitting: boolean,
                promptName: string | null,
                versionSlots: VersionSlots
            ): boolean => {
                if (submitting || selectedTemplates.length === 0 || !promptName) {
                    return false
                }
                if (versions.length < MIN_VERSIONS) {
                    return false
                }
                if (versionSlots.some((v) => v === null)) {
                    return false
                }
                return new Set(versions).size === versions.length
            },
        ],
        disabledVersionsByIndex: [
            (s) => [s.versionSlots],
            (slots: VersionSlots): Set<number>[] =>
                slots.map((_, i) => {
                    const others = new Set<number>()
                    slots.forEach((v, j) => {
                        if (j !== i && v !== null) {
                            others.add(v)
                        }
                    })
                    return others
                }),
        ],
        canAddSlot: [
            (s) => [s.versionSlots],
            (slots: VersionSlots): boolean => slots.length < MAX_VERSIONS && slots.every((v) => v !== null),
        ],
    }),

    listeners(({ values, actions }) => ({
        openModal: () => {
            posthog.capture('llma prompt experiment modal opened', {
                prompt_name: values.promptName,
                prompt_total_versions: values.promptVersions.length,
            })
            if (values.templates.length === 0) {
                actions.loadTemplates()
            } else if (values.selectedTemplates.length === 0) {
                actions.setSelectedTemplates(values.templates.map((t) => t.key as TemplatesEnumApi))
            }
        },
        loadTemplatesSuccess: () => {
            // Pre-select every template by default — users typically want all of them on a
            // new prompt experiment and can uncheck the ones they don't want.
            if (values.isModalOpen && values.selectedTemplates.length === 0) {
                actions.setSelectedTemplates(values.templates.map((t) => t.key as TemplatesEnumApi))
            }
        },
        submitCreate: async () => {
            if (!values.promptName) {
                const message = 'No prompt selected. Close and reopen the modal.'
                actions.submitCreateFailure(message)
                lemonToast.error(message)
                return
            }
            if (values.selectedTemplates.length === 0) {
                const message = 'Pick at least one metric template before submitting.'
                actions.submitCreateFailure(message)
                lemonToast.error(message)
                return
            }
            if (values.selectedVersions.length < MIN_VERSIONS) {
                const message = `Pick at least ${MIN_VERSIONS} versions.`
                actions.submitCreateFailure(message)
                lemonToast.error(message)
                return
            }
            try {
                const experiment = await experimentsCreateFromPromptCreate(String(ApiConfig.getCurrentTeamId()), {
                    prompt_name: values.promptName,
                    versions: values.selectedVersions,
                    templates: values.selectedTemplates,
                })
                actions.submitCreateSuccess(experiment.id)
                lemonToast.success('Experiment created', {
                    button: {
                        label: 'Open',
                        action: () => router.actions.push(urls.experiment(experiment.id)),
                    },
                })
                actions.closeModal()
            } catch (error) {
                const message = extractApiErrorMessage(error)
                actions.submitCreateFailure(message)
                lemonToast.error(message)
            }
        },
        submitCreateSuccess: ({ experimentId }) => {
            posthog.capture('llma prompt experiment created', {
                experiment_id: experimentId,
                prompt_name: values.promptName,
                versions: values.selectedVersions,
                templates: values.selectedTemplates,
                prompt_total_versions: values.promptVersions.length,
            })
        },
        submitCreateFailure: ({ error }) => {
            posthog.capture('llma prompt experiment creation failed', {
                prompt_name: values.promptName,
                error_message: error.slice(0, 200),
            })
        },
    })),
])

function extractApiErrorMessage(error: unknown): string {
    if (error !== null && typeof error === 'object') {
        if ('detail' in error && typeof (error as { detail?: unknown }).detail === 'string') {
            return (error as { detail: string }).detail
        }
        if (error instanceof Error && error.message) {
            return error.message
        }
    }
    return 'Failed to create experiment from prompt.'
}
