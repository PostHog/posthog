import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { PROVIDER_SETTINGS_URL } from './ModelPicker'
import { modelPickerLogic } from './modelPickerLogic'
import { providerLabel } from './settings/providerKeyStateUtils'

/** Explains an empty or short model picker on the surfaces that only run on the team's own provider keys. */
export function ByokModelPickerNotice(): JSX.Element | null {
    const { byokModelNotice } = useValues(modelPickerLogic)
    const { loadByokModels } = useActions(modelPickerLogic)

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
        case 'no-keys':
            return (
                <p className="text-xs text-secondary mt-1">
                    No models available. <Link to={PROVIDER_SETTINGS_URL}>Add your own API keys</Link> to choose one.
                </p>
            )
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
