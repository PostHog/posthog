import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { llmProviderKeysLogic } from './llmProviderKeysLogic'

export function SystemOneConnectionFields(): JSX.Element {
    const { systemOneBaseUrl, systemOneModel, providerKeysLoading } = useValues(llmProviderKeysLogic)
    const { setSystemOneBaseUrl, setSystemOneModel } = useActions(llmProviderKeysLogic)

    return (
        <div className="space-y-3">
            <div>
                <LemonLabel htmlFor="system-one-base-url">Base URL</LemonLabel>
                <LemonInput
                    id="system-one-base-url"
                    value={systemOneBaseUrl}
                    onChange={setSystemOneBaseUrl}
                    disabled={providerKeysLoading}
                    placeholder="https://decisions.example.com/v1"
                    data-attr="system-one-base-url"
                    fullWidth
                />
            </div>
            <div>
                <LemonLabel htmlFor="system-one-model">Model ID</LemonLabel>
                <LemonInput
                    id="system-one-model"
                    value={systemOneModel}
                    onChange={setSystemOneModel}
                    disabled={providerKeysLoading}
                    placeholder="Your model ID"
                    data-attr="system-one-model"
                    fullWidth
                />
            </div>
            <p className="text-xs text-muted">
                Use a public HTTPS endpoint that supports the System One API. Include /v1 in the base URL if your
                service requires it. Validation sends a short synthetic example to the selected model.
            </p>
        </div>
    )
}
