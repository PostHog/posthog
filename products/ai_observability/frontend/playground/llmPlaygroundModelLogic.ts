import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { modelPickerLogic, type ModelOption } from '../modelPickerLogic'
import { LLMProviderKey, llmProviderKeysLogic, normalizeLLMProvider } from '../settings/llmProviderKeysLogic'
import type { llmPlaygroundModelLogicType } from './llmPlaygroundModelLogicType'
import { llmPlaygroundPromptsLogic, type PromptConfig } from './llmPlaygroundPromptsLogic'
import {
    isTraceLikeSelection,
    matchClosestModel,
    matchClosestModelOption,
    type MatchModelOption,
    resolveProviderKeyForPrompt,
    resolveTraceModelSelection,
} from './playgroundModelMatching'

function normalizePromptsToAvailableModels(
    promptConfigs: PromptConfig[],
    pendingTargetModel: string | null,
    availableModels: MatchModelOption[],
    providerKeys: LLMProviderKey[]
): PromptConfig[] {
    return promptConfigs.map((prompt: PromptConfig, index: number) => {
        const targetModel = index === 0 && pendingTargetModel ? pendingTargetModel : prompt.model
        const matchedModel = matchClosestModelOption(targetModel, availableModels, providerKeys)
        return {
            ...prompt,
            model:
                index === 0 && pendingTargetModel
                    ? (matchedModel?.id ?? pendingTargetModel)
                    : (matchedModel?.id ?? matchClosestModel(targetModel, availableModels)),
            selectedProviderKeyId: matchedModel?.providerKeyId ?? prompt.selectedProviderKeyId,
        }
    })
}

export type LLMPlaygroundModelLogicProps = Record<string, never>

export const llmPlaygroundModelLogic = kea<llmPlaygroundModelLogicType>([
    path(['products', 'ai_observability', 'frontend', 'playground', 'llmPlaygroundModelLogic']),
    props({} as LLMPlaygroundModelLogicProps),

    connect(() => ({
        values: [
            llmPlaygroundPromptsLogic,
            [
                'promptConfigs',
                'activePromptConfig',
                'pendingTargetModel',
                'pendingTargetProvider',
                'pendingTargetIsTrace',
            ],
            modelPickerLogic,
            [
                'byokModels',
                'byokModelsLoading',
                'trialModels',
                'trialModelsLoading',
                'hasByokKeys',
                'trialProviderModelGroups',
            ],
            llmProviderKeysLogic,
            ['providerKeys', 'providerKeysLoading'],
        ],
        actions: [
            llmPlaygroundPromptsLogic,
            ['setupPlaygroundFromEvent', 'setModel', 'setPromptConfigs', 'clearPendingTargetModel'],
            modelPickerLogic,
            ['loadByokModelsSuccess', 'loadByokModelsFailure', 'loadTrialModelsSuccess', 'loadTrialModelsFailure'],
            llmProviderKeysLogic,
            ['loadProviderKeys', 'loadProviderKeysSuccess', 'loadProviderKeysFailure'],
        ],
    })),

    actions({
        setActiveProviderKeyId: (id: string | null) => ({ id }),
    }),

    reducers({
        trialModelsErrorStatus: [
            null as number | null,
            {
                loadTrialModelsSuccess: () => null,
                loadTrialModelsFailure: (_: number | null, { error }: { error: unknown }) => {
                    if (error instanceof ApiError) {
                        return error.status ?? null
                    }
                    return null
                },
            },
        ],
        activeProviderKeyId: [
            null as string | null,
            {
                setActiveProviderKeyId: (_: string | null, { id }: { id: string | null }) => id,
            },
        ],
        providerKeysSettled: [
            false as boolean,
            {
                loadProviderKeys: () => false,
                loadProviderKeysSuccess: () => true,
                loadProviderKeysFailure: () => true,
            },
        ],
        byokModelsSettled: [
            false as boolean,
            {
                loadProviderKeys: () => false,
                loadProviderKeysSuccess: (_: boolean, { providerKeys }: { providerKeys: LLMProviderKey[] }) =>
                    !providerKeys.some((key) => key.state === 'ok'),
                loadByokModelsSuccess: () => true,
                loadByokModelsFailure: () => true,
            },
        ],
        trialModelsSettled: [
            false as boolean,
            {
                loadTrialModelsSuccess: () => true,
                loadTrialModelsFailure: () => true,
            },
        ],
    }),

    loaders(() => ({
        evaluationConfig: {
            __default: null as { active_provider_key: { id: string } | null } | null,
            loadEvaluationConfig: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return null
                }
                try {
                    // nosemgrep: prefer-codegen-api
                    return (await api.get(`/api/environments/${teamId}/llm_analytics/evaluation_config/`)) as {
                        active_provider_key: { id: string } | null
                    }
                } catch (e) {
                    console.warn('Failed to load evaluation config', e)
                    return null
                }
            },
        },
    })),

    selectors({
        effectiveModelOptions: [
            (s) => [s.hasByokKeys, s.byokModels, s.trialModels],
            (hasByokKeys: boolean, byokModels: ModelOption[], trialModels: ModelOption[]): ModelOption[] =>
                hasByokKeys && byokModels.length > 0 ? byokModels : trialModels,
        ],
        allModelOptions: [
            (s) => [s.trialModels, s.byokModels],
            (trialModels: ModelOption[], byokModels: ModelOption[]): ModelOption[] => [...trialModels, ...byokModels],
        ],
        providerKeyForCurrentModel: [
            (s) => [s.activePromptConfig, s.effectiveModelOptions, s.providerKeys],
            (
                activePromptConfig: PromptConfig,
                modelOptions: ModelOption[],
                providerKeys: LLMProviderKey[]
            ): LLMProviderKey | null => resolveProviderKeyForPrompt(activePromptConfig, modelOptions, providerKeys),
        ],
        hasProviderKey: [(s) => [s.providerKeyForCurrentModel], (key: LLMProviderKey | null): boolean => key !== null],
    }),

    listeners(({ actions, values }) => {
        const applyTraceSelection = (targetModel: string, promptId: string, provider: string | null): void => {
            const { resolvedModelId, providerKeyId } = resolveTraceModelSelection(
                targetModel,
                provider,
                values.allModelOptions,
                values.providerKeys
            )
            actions.setModel(resolvedModelId, providerKeyId, promptId)
        }

        const applyPendingTraceSelection = (targetModel: string): void => {
            const promptId = values.promptConfigs[0]?.id
            if (!promptId) {
                actions.clearPendingTargetModel()
                return
            }
            applyTraceSelection(targetModel, promptId, values.pendingTargetProvider)
            actions.clearPendingTargetModel()
        }

        // Resolve a pending target model once provider keys, BYOK models, and trial models have
        // all settled — whichever of those loads last drives the resolution. Previously this only
        // ran from the trial/BYOK success handlers, so a pending model was silently dropped when
        // trial models loaded before provider keys settled and there were no BYOK keys to fire
        // loadByokModelsSuccess (the resolution would bail on the settled-gate and never retry).
        const resolvePendingTarget = (): void => {
            const pendingTargetModel = values.pendingTargetModel
            if (!pendingTargetModel) {
                return
            }
            if (!values.providerKeysSettled || !values.byokModelsSettled || !values.trialModelsSettled) {
                return
            }
            if (values.pendingTargetIsTrace) {
                applyPendingTraceSelection(pendingTargetModel)
                return
            }
            const normalizedPromptsWithTarget = normalizePromptsToAvailableModels(
                values.promptConfigs,
                pendingTargetModel,
                values.effectiveModelOptions,
                values.providerKeys
            )
            actions.setPromptConfigs(normalizedPromptsWithTarget)
            actions.clearPendingTargetModel()
        }

        return {
            loadEvaluationConfigSuccess: ({
                evaluationConfig,
            }: {
                evaluationConfig: { active_provider_key: { id: string } | null } | null
            }) => {
                actions.setActiveProviderKeyId(evaluationConfig?.active_provider_key?.id ?? null)
            },
            loadTrialModelsSuccess: ({ trialModels }: { trialModels: ModelOption[] }) => {
                if (trialModels.length === 0) {
                    return
                }

                // Normalize prompts to available trial models
                const pendingTargetModel = values.pendingTargetModel

                const normalizedPrompts = values.promptConfigs.map((prompt, index) => {
                    if (index === 0 && pendingTargetModel) {
                        return prompt
                    }
                    if (values.hasByokKeys && prompt.selectedProviderKeyId) {
                        return prompt
                    }

                    const closestMatch = matchClosestModel(prompt.model, trialModels)
                    if (prompt.model === closestMatch) {
                        return prompt
                    }
                    return {
                        ...prompt,
                        model: closestMatch,
                        selectedProviderKeyId: null,
                    }
                })

                const changed = normalizedPrompts.some((prompt, index) => prompt !== values.promptConfigs[index])
                if (changed) {
                    actions.setPromptConfigs(normalizedPrompts)
                }

                resolvePendingTarget()
            },
            loadProviderKeysSuccess: () => {
                // If trial models loaded before provider keys settled, the trial handler couldn't
                // resolve the pending target yet. Retry now that keys (and the BYOK-settled flag) are in.
                resolvePendingTarget()
            },
            loadProviderKeysFailure: () => resolvePendingTarget(),
            loadTrialModelsFailure: () => resolvePendingTarget(),
            loadByokModelsFailure: () => resolvePendingTarget(),
            loadByokModelsSuccess: ({ byokModels }: { byokModels: ModelOption[] }) => {
                if (byokModels.length === 0) {
                    return
                }

                const targetModelForFirstPrompt = values.pendingTargetModel
                if (targetModelForFirstPrompt && values.pendingTargetIsTrace) {
                    applyPendingTraceSelection(targetModelForFirstPrompt)
                    return
                }
                const normalizedPrompts = normalizePromptsToAvailableModels(
                    values.promptConfigs,
                    targetModelForFirstPrompt,
                    byokModels,
                    values.providerKeys
                )

                actions.setPromptConfigs(normalizedPrompts)
                actions.clearPendingTargetModel()
            },
            setupPlaygroundFromEvent: ({ payload }: { payload: { model?: string; provider?: string } }) => {
                const { model, provider } = payload
                const currentPrompt = values.promptConfigs[0]
                const promptId = currentPrompt?.id
                if (!promptId || !model) {
                    return
                }

                if (!values.providerKeysSettled || !values.byokModelsSettled) {
                    return
                }

                const traceLikeSelection = isTraceLikeSelection(model, provider)
                if (traceLikeSelection) {
                    const { resolvedModelId, providerKeyId } = resolveTraceModelSelection(
                        model,
                        normalizeLLMProvider(provider),
                        values.allModelOptions,
                        values.providerKeys
                    )
                    actions.setModel(resolvedModelId, providerKeyId, promptId)
                } else {
                    const matchedModel = matchClosestModelOption(
                        model,
                        values.effectiveModelOptions,
                        values.providerKeys
                    )
                    actions.setModel(matchedModel?.id ?? model, matchedModel?.providerKeyId, promptId)
                }
                actions.clearPendingTargetModel()
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadEvaluationConfig()
    }),
])
