import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { llmProviderKeysLogic } from './llmProviderKeysLogic'

export function SystemOneConnectionFields(): JSX.Element {
    const { systemOneBaseUrl, systemOneModel, providerKeysLoading, keyFieldError } = useValues(llmProviderKeysLogic)
    const { setSystemOneBaseUrl, setSystemOneModel } = useActions(llmProviderKeysLogic)
    const baseUrlError = keyFieldError?.field === 'base_url' ? keyFieldError.message : null
    const modelError = keyFieldError?.field === 'system_one_model' ? keyFieldError.message : null

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
                    status={baseUrlError ? 'danger' : undefined}
                />
                {baseUrlError && <p className="text-xs text-danger mt-1">{baseUrlError}</p>}
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
                    status={modelError ? 'danger' : undefined}
                />
                {modelError && <p className="text-xs text-danger mt-1">{modelError}</p>}
            </div>
            <p className="text-xs text-muted">
                Enter the public HTTPS base URL, ending before /systemone. Validation sends a short synthetic example to
                the selected model.
            </p>
        </div>
    )
}
