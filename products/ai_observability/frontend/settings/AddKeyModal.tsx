import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LLM_PROVIDER_SELECT_OPTIONS } from '../LLMProviderIcon'
import { FoundryEndpointField } from './FoundryEndpointField'
import { KeyValidationStatus } from './KeyValidationStatus'
import {
    CreateLLMProviderKeyPayload,
    DEFAULT_AZURE_API_VERSION,
    LLMProvider,
    llmProviderKeysLogic,
} from './llmProviderKeysLogic'
import { endpointErrorFieldFromResult, getKeyPlaceholder } from './providerKeyStateUtils'
import { SystemOneConnectionFields } from './SystemOneConnectionFields'

export function AddKeyModal({ restrictionReason }: { restrictionReason: string | null }): JSX.Element {
    const { systemOneBaseUrl, systemOneModel } = useValues(llmProviderKeysLogic)
    const { newKeyModalOpen, providerKeysLoading, preValidationResult, preValidationResultLoading, evaluationConfig } =
        useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, createProviderKey, preValidateKey, clearPreValidation } =
        useActions(llmProviderKeysLogic)

    const [provider, setProvider] = useState<LLMProvider>('openai')
    const [name, setName] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [azureEndpoint, setAzureEndpoint] = useState('')
    const [apiVersion, setApiVersion] = useState(DEFAULT_AZURE_API_VERSION)
    const [baseUrl, setBaseUrl] = useState('')
    const [pendingSubmit, setPendingSubmit] = useState(false)

    const isAzure = provider === 'azure_openai'
    const isAnthropic = provider === 'anthropic'
    const isOpenAICompatible = provider === 'openai_compatible'
    const hasEndpointField = isAzure || isAnthropic || isOpenAICompatible
    // Anthropic keys take an optional Microsoft Foundry endpoint, so only send one that was entered.
    const endpointPayload = isAzure
        ? { azure_endpoint: azureEndpoint, api_version: apiVersion }
        : isAnthropic && azureEndpoint
          ? { azure_endpoint: azureEndpoint }
          : {}
    const keyValidated = preValidationResult?.state === 'ok'
    const isSystemOne = provider === 'system_one'
    const isValid =
        name.trim().length > 0 &&
        (isSystemOne ? systemOneBaseUrl.length > 0 && systemOneModel.length > 0 : apiKey.length > 0) &&
        (!isAzure || (azureEndpoint.trim().length > 0 && apiVersion.trim().length > 0)) &&
        (!isOpenAICompatible || baseUrl.trim().length > 0)
    const validationFailed = !!preValidationResult && preValidationResult.state !== 'ok'
    const endpointErrorField =
        hasEndpointField && validationFailed ? endpointErrorFieldFromResult(preValidationResult) : null

    // Reset form when modal closes
    useEffect(() => {
        if (!newKeyModalOpen) {
            setProvider('openai')
            setName('')
            setApiKey('')
            setAzureEndpoint('')
            setApiVersion(DEFAULT_AZURE_API_VERSION)
            setBaseUrl('')
            setPendingSubmit(false)
        }
    }, [newKeyModalOpen])

    // Auto-submit after validation succeeds if submit was pending
    useEffect(() => {
        if (pendingSubmit && preValidationResult && !preValidationResultLoading) {
            setPendingSubmit(false)
            if (preValidationResult.state === 'ok') {
                const payload: CreateLLMProviderKeyPayload = {
                    provider,
                    name,
                    api_key: apiKey,
                    set_as_active: provider !== 'system_one' && !evaluationConfig?.active_provider_key,
                    ...endpointPayload,
                }
                if (isOpenAICompatible) {
                    payload.base_url = baseUrl
                }
                createProviderKey({ payload })
            }
        }
    }, [
        pendingSubmit,
        preValidationResult,
        preValidationResultLoading,
        createProviderKey,
        name,
        apiKey,
        provider,
        isAzure,
        isAnthropic,
        azureEndpoint,
        apiVersion,
        isOpenAICompatible,
        baseUrl,
        evaluationConfig?.active_provider_key,
    ]) // oxlint-disable-line react-hooks/exhaustive-deps

    const handleClose = (): void => {
        setNewKeyModalOpen(false)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        if (isSystemOne) {
            createProviderKey({
                payload: {
                    provider,
                    name,
                    api_key: apiKey,
                    base_url: systemOneBaseUrl,
                    system_one_model: systemOneModel,
                },
            })
            return
        }
        if (keyValidated) {
            const payload: CreateLLMProviderKeyPayload = {
                provider,
                name,
                api_key: apiKey,
                set_as_active: !evaluationConfig?.active_provider_key,
                ...endpointPayload,
            }
            if (isOpenAICompatible) {
                payload.base_url = baseUrl
            }
            createProviderKey({ payload })
        } else if (apiKey.length > 0) {
            setPendingSubmit(true)
            preValidateKey({
                apiKey,
                provider,
                ...endpointPayload,
                ...(isOpenAICompatible ? { base_url: baseUrl } : {}),
            })
        }
    }

    const handleApiKeyBlur = (): void => {
        if (isSystemOne) {
            return
        }
        if (apiKey.length > 0 && !preValidationResult) {
            preValidateKey({
                apiKey,
                provider,
                ...endpointPayload,
                ...(isOpenAICompatible ? { base_url: baseUrl } : {}),
            })
        }
    }

    const handleApiKeyChange = (value: string): void => {
        setApiKey(value)
        if (preValidationResult) {
            clearPreValidation()
        }
    }

    // A result is only about the endpoint it was validated against, so editing the endpoint has
    // to drop it. Otherwise a key validated against the old endpoint keeps showing as validated.
    const handleEndpointChange =
        (setEndpoint: (value: string) => void): ((value: string) => void) =>
        (value) => {
            setEndpoint(value)
            if (preValidationResult) {
                clearPreValidation()
            }
        }

    const handleProviderChange = (value: LLMProvider): void => {
        setProvider(value)
        setApiKey('')
        setAzureEndpoint('')
        setApiVersion(DEFAULT_AZURE_API_VERSION)
        setBaseUrl('')
        clearPreValidation()
    }

    return (
        <LemonModal
            isOpen={newKeyModalOpen}
            onClose={handleClose}
            title="Add API key"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={providerKeysLoading || preValidationResultLoading}
                        disabled={!isValid}
                        disabledReason={restrictionReason}
                    >
                        Add key
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Provider</label>
                    <LemonSelect
                        value={provider}
                        onChange={handleProviderChange}
                        options={LLM_PROVIDER_SELECT_OPTIONS}
                        className="mt-1"
                        fullWidth
                    />
                </div>
                {isAzure && (
                    <>
                        <div>
                            <label className="text-sm font-medium">Azure endpoint</label>
                            <LemonInput
                                value={azureEndpoint}
                                onChange={setAzureEndpoint}
                                placeholder="https://my-resource.openai.azure.com/"
                                className="mt-1"
                                fullWidth
                                status={endpointErrorField === 'endpoint' ? 'danger' : undefined}
                            />
                            {endpointErrorField === 'endpoint' ? (
                                <p className="text-xs text-danger mt-1">
                                    {preValidationResult?.error_message || 'Invalid Azure endpoint'}
                                </p>
                            ) : (
                                <p className="text-xs text-muted mt-1">
                                    The endpoint URL of your Azure OpenAI resource
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="text-sm font-medium">API version</label>
                            <LemonInput
                                value={apiVersion}
                                onChange={setApiVersion}
                                placeholder={DEFAULT_AZURE_API_VERSION}
                                className="mt-1"
                                fullWidth
                            />
                            <p className="text-xs text-muted mt-1">
                                Azure OpenAI API version (defaults to {DEFAULT_AZURE_API_VERSION})
                            </p>
                        </div>
                    </>
                )}
                {isAnthropic && (
                    <FoundryEndpointField
                        optional
                        value={azureEndpoint}
                        onChange={handleEndpointChange(setAzureEndpoint)}
                        errorMessage={
                            endpointErrorField === 'endpoint'
                                ? preValidationResult?.error_message || 'Invalid Microsoft Foundry endpoint'
                                : null
                        }
                    />
                )}
                {isSystemOne && <SystemOneConnectionFields />}
                {isOpenAICompatible && (
                    <div>
                        <label className="text-sm font-medium">Base URL</label>
                        <LemonInput
                            value={baseUrl}
                            onChange={handleEndpointChange(setBaseUrl)}
                            placeholder="https://api.example.com/v1"
                            className="mt-1"
                            fullWidth
                            status={endpointErrorField === 'endpoint' ? 'danger' : undefined}
                        />
                        {endpointErrorField === 'endpoint' ? (
                            <p className="text-xs text-danger mt-1">
                                {preValidationResult?.error_message || 'Invalid base URL'}
                            </p>
                        ) : (
                            <p className="text-xs text-muted mt-1">
                                The base URL of your OpenAI-compatible API. Must be a public https:// URL that serves
                                the /models and /chat/completions endpoints.
                            </p>
                        )}
                    </div>
                )}
                <div>
                    <label className="text-sm font-medium">Name</label>
                    <LemonInput
                        value={name}
                        onChange={setName}
                        placeholder="e.g. Production key"
                        className="mt-1"
                        fullWidth
                    />
                    <p className="text-xs text-muted mt-1">A friendly name to identify this key</p>
                </div>
                <div>
                    <label className="text-sm font-medium">API key</label>
                    <LemonInput
                        value={apiKey}
                        onChange={handleApiKeyChange}
                        onBlur={handleApiKeyBlur}
                        placeholder={getKeyPlaceholder(provider, isAnthropic && azureEndpoint.length > 0)}
                        type="password"
                        autoComplete="off"
                        className="mt-1"
                        fullWidth
                        status={
                            validationFailed && (!hasEndpointField || endpointErrorField === 'key')
                                ? 'danger'
                                : undefined
                        }
                    />
                    <KeyValidationStatus
                        result={preValidationResult}
                        isValidating={preValidationResultLoading}
                        provider={provider}
                        suppressError={endpointErrorField === 'endpoint'}
                        usesFoundry={isAnthropic && azureEndpoint.length > 0}
                    />
                    {isSystemOne && (
                        <p className="text-xs text-muted">
                            Sent as a bearer token. Leave empty only if your custom endpoint does not require
                            authentication.
                        </p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
