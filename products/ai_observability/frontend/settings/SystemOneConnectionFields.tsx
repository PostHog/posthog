import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { llmProviderKeysLogic } from './llmProviderKeysLogic'

export function SystemOneConnectionFields(): JSX.Element {
    const { systemOneBaseUrl, systemOneModel, providerKeysLoading } = useValues(llmProviderKeysLogic)
    const { setSystemOneBaseUrl, setSystemOneModel } = useActions(llmProviderKeysLogic)

    return (
        <details>
            <summary className="cursor-pointer text-sm font-medium">Advanced configuration</summary>
            <div className="space-y-3 mt-3">
                <div>
                    <LemonLabel htmlFor="system-one-base-url">Base URL</LemonLabel>
                    <LemonInput
                        id="system-one-base-url"
                        value={systemOneBaseUrl}
                        onChange={setSystemOneBaseUrl}
                        disabled={providerKeysLoading}
                        placeholder="https://api.typesafe.ai/v1"
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
                        placeholder="jev-1.13.0"
                        data-attr="system-one-model"
                        fullWidth
                    />
                </div>
                <p className="text-xs text-muted">
                    Defaults to TypeSafe's hosted service and the Jev model. Use a public HTTPS endpoint that supports
                    the System One API. Include /v1 in the base URL if required by your service. Validation sends a
                    short synthetic example to the selected model.
                </p>
            </div>
        </details>
    )
}
