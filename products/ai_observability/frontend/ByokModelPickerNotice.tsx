import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { PROVIDER_SETTINGS_URL } from './ModelPicker'
import { modelPickerLogic } from './modelPickerLogic'
import { llmProviderKeysLogic } from './settings/llmProviderKeysLogic'
import { LLMProviderKeysSettings } from './settings/LLMProviderKeysSettings'
import { providerLabel } from './settings/providerKeyStateUtils'

/** Explains an empty or short model picker on the surfaces that only run on the team's own provider keys. */
export function ByokModelPickerNotice({ forEvaluation = false }: { forEvaluation?: boolean }): JSX.Element | null {
    const { byokModelNotice: generativeModelNotice, evaluationModelNotice } = useValues(modelPickerLogic)
    const byokModelNotice = forEvaluation ? evaluationModelNotice : generativeModelNotice
    const { loadByokModels } = useActions(modelPickerLogic)
    const { newKeyModalOpen, providerKeys } = useValues(llmProviderKeysLogic)

    // Saving a key reloads the keys, which clears the notice for a moment. Keep the view mounted
    // while its add-key modal is open, so a failed save keeps what the person typed.
    if (byokModelNotice?.kind === 'no-keys' || (newKeyModalOpen && providerKeys.length === 0)) {
        return (
            <div className="mt-2">
                <LLMProviderKeysSettings />
            </div>
        )
    }

    switch (byokModelNotice?.kind) {
        case 'models-failed': {
            const [firstKey] = byokModelNotice.keys
            return (
                <LemonBanner
                    type="error"
                    className="mt-1 text-xs"
                    action={{ onClick: loadByokModels, children: 'Try again', 'data-attr': 'byok-models-retry' }}
                >
                    {byokModelNotice.keys.length === 1 ? (
                        <>
                            Couldn't load models for API key <span className="font-semibold">{firstKey.name}</span> (
                            {providerLabel(firstKey.provider)}).
                        </>
                    ) : (
                        `Couldn't load models for ${byokModelNotice.keys.length} of your API keys.`
                    )}
                </LemonBanner>
            )
        }
        case 'deployments-unlisted': {
            const [firstKey] = byokModelNotice.keys
            return (
                <p className="text-xs text-secondary mt-1">
                    {byokModelNotice.keys.length === 1 ? (
                        <>
                            Azure OpenAI didn't list any deployments for API key{' '}
                            <span className="font-semibold">{firstKey.name}</span>.
                        </>
                    ) : (
                        `Azure OpenAI didn't list any deployments for ${byokModelNotice.keys.length} of your API keys.`
                    )}{' '}
                    Type your deployment name in the model search to use it.
                </p>
            )
        }
        case 'no-usable-keys':
            return (
                <p className="text-xs text-secondary mt-1">
                    No models available because none of your API keys are ready.{' '}
                    <Link to={PROVIDER_SETTINGS_URL}>Check your API keys</Link>.
                </p>
            )
        default:
            return null
    }
}
