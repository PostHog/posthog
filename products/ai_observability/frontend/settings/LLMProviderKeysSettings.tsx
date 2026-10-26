import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { IconKey } from 'lib/lemon-ui/icons'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LLMProviderIcon, LLM_PROVIDER_SELECT_OPTIONS } from '../LLMProviderIcon'
import {
    AlternativeKey,
    CreateLLMProviderKeyPayload,
    DEFAULT_AZURE_API_VERSION,
    DEFAULT_SYSTEM_ONE_BASE_URL,
    DEFAULT_SYSTEM_ONE_MODEL,
    DependentConfigsResponse,
    EditKeyField,
    KeyValidationResult,
    LLMProvider,
    LLMProviderKey,
    LLMProviderKeyState,
    LLM_PROVIDER_LABELS,
    UpdateLLMProviderKeyPayload,
    isFoundryKey,
    llmProviderKeysLogic,
    normalizeSystemOneBaseUrlForComparison,
    sortProviderKeys,
} from './llmProviderKeysLogic'
import { SystemOneConnectionFields } from './SystemOneConnectionFields'

function StateTag({ state, errorMessage }: { state: LLMProviderKeyState; errorMessage: string | null }): JSX.Element {
    const tagProps: { type: 'success' | 'danger' | 'warning' | 'default'; children: string } = {
        type: 'default',
        children: 'Unknown',
    }

    switch (state) {
        case 'ok':
            tagProps.type = 'success'
            tagProps.children = 'Valid'
            break
        case 'invalid':
            tagProps.type = 'danger'
            tagProps.children = 'Invalid'
            break
        case 'error':
            tagProps.type = 'warning'
            tagProps.children = 'Error'
            break
        case 'unknown':
            tagProps.type = 'default'
            tagProps.children = 'Unknown'
            break
    }

    const tag = <LemonTag type={tagProps.type}>{tagProps.children}</LemonTag>

    if (errorMessage && (state === 'invalid' || state === 'error')) {
        return <Tooltip title={errorMessage}>{tag}</Tooltip>
    }

    return tag
}

function formatDate(dateString: string | null): string {
    if (!dateString) {
        return 'Never'
    }
    return new Date(dateString).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    })
}

function getKeyPlaceholder(provider: LLMProvider, usesFoundry = false): string {
    switch (provider) {
        case 'openai':
            return 'sk-...'
        case 'anthropic':
            return usesFoundry ? 'Enter your Microsoft Foundry API key' : 'sk-ant-...'
        case 'gemini':
            return 'Enter your Gemini API key'
        case 'together_ai':
            return 'Enter your Together AI API key'
        case 'openrouter':
            return 'Enter your OpenRouter API key'
        case 'fireworks':
            return 'Enter your Fireworks API key'
        case 'azure_openai':
            return 'Enter your Azure OpenAI API key'
        case 'minimax':
            return 'Enter your MiniMax API key'
        case 'system_one':
            return "Enter your endpoint's bearer token"
        case 'openai_compatible':
            return 'Enter your API key'
    }
}

// Azure and OpenAI-compatible validation errors can originate from either the endpoint or the
// API key. The backend tells us which via `error_field`; map it to which input this component
// highlights.
function endpointErrorFieldFromResult(result: KeyValidationResult | null | undefined): 'endpoint' | 'key' | null {
    if (!result || result.state === 'ok') {
        return null
    }
    return result.error_field === 'azure_endpoint' || result.error_field === 'base_url' ? 'endpoint' : 'key'
}

function TextField({
    label,
    value,
    onChange,
    placeholder,
    error,
}: {
    label: string
    value: string
    onChange: (value: string) => void
    placeholder?: string
    error: string | null
}): JSX.Element {
    return (
        <div>
            <label className="text-sm font-medium">{label}</label>
            <LemonInput
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                className="mt-1"
                fullWidth
                status={error ? 'danger' : undefined}
            />
            {error && <p className="text-xs text-danger mt-1">{error}</p>}
        </div>
    )
}

function FoundryEndpointField({
    value,
    onChange,
    errorMessage,
    optional,
}: {
    value: string
    onChange: (value: string) => void
    errorMessage: string | null
    optional: boolean
}): JSX.Element {
    return (
        <div>
            <label className="text-sm font-medium">
                {optional ? 'Microsoft Foundry endpoint (optional)' : 'Microsoft Foundry endpoint'}
            </label>
            <LemonInput
                value={value}
                onChange={onChange}
                placeholder="https://my-resource.services.ai.azure.com/"
                className="mt-1"
                fullWidth
                status={errorMessage ? 'danger' : undefined}
            />
            {errorMessage ? (
                <p className="text-xs text-danger mt-1">{errorMessage}</p>
            ) : (
                <p className="text-xs text-muted mt-1">
                    {optional
                        ? 'Fill this in only if you run Claude on Microsoft Foundry. Leave it empty for a key from the Anthropic API.'
                        : 'The endpoint URL of your Microsoft Foundry resource'}
                </p>
            )}
        </div>
    )
}

function KeyValidationStatus({
    result,
    isValidating,
    provider,
    suppressError = false,
    usesFoundry = false,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
    provider: LLMProvider
    suppressError?: boolean
    usesFoundry?: boolean
}): JSX.Element | null {
    if (isValidating) {
        return <p className="text-xs text-muted mt-1">Validating key...</p>
    }

    const providerLabel =
        provider === 'openai_compatible' ? 'your provider' : usesFoundry ? 'Microsoft' : LLM_PROVIDER_LABELS[provider]
    const bullets = (
        <ul className="text-xs text-muted mt-1 list-disc pl-4 space-y-0.5">
            <li>Your key will be encrypted and stored securely</li>
            <li>
                {provider === 'system_one'
                    ? 'Model usage is billed by your endpoint provider'
                    : `You pay ${providerLabel} directly for model usage`}
            </li>
            <li>Each evaluation counts as an AI observability event</li>
        </ul>
    )

    if (!result) {
        return bullets
    }

    if (result.state === 'ok') {
        return <p className="text-xs text-success mt-1">Key validated successfully</p>
    }

    return (
        <>
            {bullets}
            {!suppressError && (
                <p className="text-xs text-danger mt-1">{result.error_message || 'Key validation failed'}</p>
            )}
        </>
    )
}

function AddKeyModal({ restrictionReason }: { restrictionReason: string | null }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
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
                        options={LLM_PROVIDER_SELECT_OPTIONS.filter(
                            ({ value }) =>
                                value !== 'system_one' ||
                                featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SYSTEM_ONE_EVALUATIONS] === true
                        )}
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

function EditKeyModal({
    keyToEdit,
    restrictionReason,
}: {
    keyToEdit: LLMProviderKey
    restrictionReason: string | null
}): JSX.Element {
    const { providerKeysLoading, preValidationResult, preValidationResultLoading, editKeyFieldError } =
        useValues(llmProviderKeysLogic)
    const { systemOneBaseUrl, systemOneModel } = useValues(llmProviderKeysLogic)
    const { setEditingKey, updateProviderKey, preValidateKey, clearPreValidation, setEditKeyFieldError } =
        useActions(llmProviderKeysLogic)
    const isAzureEdit = keyToEdit.provider === 'azure_openai'
    const isSystemOne = keyToEdit.provider === 'system_one'
    const endpointChanged =
        normalizeSystemOneBaseUrlForComparison(systemOneBaseUrl) !==
        normalizeSystemOneBaseUrlForComparison(keyToEdit.base_url_display ?? DEFAULT_SYSTEM_ONE_BASE_URL)
    const isOpenAICompatibleEdit = keyToEdit.provider === 'openai_compatible'
    const isFoundryEdit = isFoundryKey(keyToEdit)

    const [name, setName] = useState(keyToEdit.name)
    const [apiKey, setApiKey] = useState('')
    const [azureEndpoint, setAzureEndpoint] = useState(keyToEdit.azure_endpoint_display ?? '')
    const [apiVersion, setApiVersion] = useState(keyToEdit.api_version_display ?? DEFAULT_AZURE_API_VERSION)
    const [baseUrl, setBaseUrl] = useState(keyToEdit.base_url_display ?? '')

    const fieldErrorFor = (field: EditKeyField): string | null =>
        editKeyFieldError?.field === field ? editKeyFieldError.message : null

    // A rejected field keeps its error until the user edits that field again.
    const withFieldErrorCleared =
        (field: EditKeyField, onChange: (value: string) => void): ((value: string) => void) =>
        (value) => {
            onChange(value)
            if (editKeyFieldError?.field === field) {
                setEditKeyFieldError(null)
            }
        }

    const handleClose = (): void => {
        setEditingKey(null)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        const payload: UpdateLLMProviderKeyPayload = {}
        if (name !== keyToEdit.name) {
            payload.name = name
        }
        if (apiKey.length > 0) {
            payload.api_key = apiKey
        }
        if (isSystemOne) {
            if (endpointChanged) {
                payload.base_url = systemOneBaseUrl
                payload.api_key = apiKey
            }
            if (systemOneModel !== (keyToEdit.system_one_model_display ?? DEFAULT_SYSTEM_ONE_MODEL)) {
                payload.system_one_model = systemOneModel
            }
        }
        if (isAzureEdit) {
            if (azureEndpoint !== (keyToEdit.azure_endpoint_display ?? '')) {
                payload.azure_endpoint = azureEndpoint
            }
            if (apiVersion !== (keyToEdit.api_version_display ?? DEFAULT_AZURE_API_VERSION)) {
                payload.api_version = apiVersion
            }
        }
        if (baseUrlChanged) {
            payload.base_url = baseUrl
        }
        if (foundryEndpointChanged) {
            payload.azure_endpoint = azureEndpoint
        }
        updateProviderKey({ id: keyToEdit.id, payload })
    }

    const handleApiKeyBlur = (): void => {
        if (isSystemOne) {
            return
        }
        if (apiKey.length > 0) {
            preValidateKey({
                apiKey,
                provider: keyToEdit.provider,
                ...(isAzureEdit ? { azure_endpoint: azureEndpoint, api_version: apiVersion } : {}),
                ...(isFoundryEdit ? { azure_endpoint: azureEndpoint } : {}),
                ...(isOpenAICompatibleEdit ? { base_url: baseUrl } : {}),
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

    const keyValidated = isSystemOne || apiKey.length === 0 || preValidationResult?.state === 'ok'
    const baseUrlMissing = isOpenAICompatibleEdit && baseUrl.trim().length === 0
    const foundryEndpointMissing = isFoundryEdit && azureEndpoint.trim().length === 0
    const azureEndpointMissing = isAzureEdit && azureEndpoint.trim().length === 0
    const apiVersionMissing = isAzureEdit && apiVersion.trim().length === 0
    // The backend rejects a base URL change that arrives without a key, so the key can't stay
    // masked here: re-entering it is what proves the caller already has it.
    const baseUrlChanged = isOpenAICompatibleEdit && !baseUrlMissing && baseUrl !== (keyToEdit.base_url_display ?? '')
    const foundryEndpointChanged =
        isFoundryEdit && !foundryEndpointMissing && azureEndpoint !== (keyToEdit.azure_endpoint_display ?? '')
    const apiKeyRequiredReason =
        apiKey.length > 0
            ? null
            : baseUrlChanged
              ? 'Enter the API key again to change the base URL'
              : foundryEndpointChanged
                ? 'Enter the API key again to change the Microsoft Foundry endpoint'
                : null
    const missingFieldReason =
        name.trim().length === 0
            ? 'Enter a name'
            : baseUrlMissing
              ? 'Enter a base URL'
              : foundryEndpointMissing
                ? 'Enter a Microsoft Foundry endpoint'
                : azureEndpointMissing
                  ? 'Enter an Azure endpoint'
                  : apiVersionMissing
                    ? 'Enter an API version'
                    : null
    const disabledReason = restrictionReason ?? missingFieldReason ?? apiKeyRequiredReason
    const isValid =
        keyValidated && !disabledReason && (!isSystemOne || (systemOneBaseUrl.length > 0 && systemOneModel.length > 0))
    const validationFailed = !!preValidationResult && preValidationResult.state !== 'ok'
    const hasEndpointField = isAzureEdit || isFoundryEdit || isOpenAICompatibleEdit
    const endpointErrorField =
        hasEndpointField && validationFailed ? endpointErrorFieldFromResult(preValidationResult) : null
    const endpointValidationError = endpointErrorField === 'endpoint' ? preValidationResult?.error_message : null
    const azureEndpointError =
        fieldErrorFor('azure_endpoint') ??
        (endpointErrorField === 'endpoint' ? endpointValidationError || 'Invalid Azure endpoint' : null)
    const foundryEndpointError =
        fieldErrorFor('azure_endpoint') ??
        (endpointErrorField === 'endpoint' ? endpointValidationError || 'Invalid Microsoft Foundry endpoint' : null)
    const baseUrlError =
        fieldErrorFor('base_url') ??
        (endpointErrorField === 'endpoint' ? endpointValidationError || 'Invalid base URL' : null)
    const apiVersionError = fieldErrorFor('api_version')
    const nameError = fieldErrorFor('name')
    const apiKeyError = fieldErrorFor('api_key')

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Edit API key"
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={providerKeysLoading}
                        disabled={!isValid}
                        disabledReason={disabledReason}
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Provider</label>
                    <div className="mt-1 flex items-center gap-1.5">
                        <LLMProviderIcon provider={keyToEdit.provider} />
                        <span>{LLM_PROVIDER_LABELS[keyToEdit.provider]}</span>
                    </div>
                </div>
                {isAzureEdit && (
                    <>
                        <TextField
                            label="Azure endpoint"
                            value={azureEndpoint}
                            onChange={withFieldErrorCleared('azure_endpoint', setAzureEndpoint)}
                            placeholder="https://my-resource.openai.azure.com/"
                            error={azureEndpointError}
                        />
                        <TextField
                            label="API version"
                            value={apiVersion}
                            onChange={withFieldErrorCleared('api_version', setApiVersion)}
                            placeholder={DEFAULT_AZURE_API_VERSION}
                            error={apiVersionError}
                        />
                    </>
                )}
                {isFoundryEdit && (
                    <FoundryEndpointField
                        optional={false}
                        value={azureEndpoint}
                        onChange={withFieldErrorCleared('azure_endpoint', handleEndpointChange(setAzureEndpoint))}
                        errorMessage={foundryEndpointError}
                    />
                )}
                {isSystemOne && <SystemOneConnectionFields />}
                {isOpenAICompatibleEdit && (
                    <TextField
                        label="Base URL"
                        value={baseUrl}
                        onChange={withFieldErrorCleared('base_url', handleEndpointChange(setBaseUrl))}
                        placeholder="https://api.example.com/v1"
                        error={baseUrlError}
                    />
                )}
                <TextField
                    label="Name"
                    value={name}
                    onChange={withFieldErrorCleared('name', setName)}
                    error={nameError}
                />
                <div>
                    <label className="text-sm font-medium">API key</label>
                    <LemonInput
                        value={apiKey}
                        onChange={withFieldErrorCleared('api_key', handleApiKeyChange)}
                        onBlur={handleApiKeyBlur}
                        placeholder={
                            isSystemOne && endpointChanged
                                ? "Enter the new endpoint's bearer token"
                                : `Leave empty to keep current (${keyToEdit.api_key_masked})`
                        }
                        type="password"
                        autoComplete="off"
                        className="mt-1"
                        fullWidth
                        status={
                            apiKeyError || (validationFailed && (!hasEndpointField || endpointErrorField === 'key'))
                                ? 'danger'
                                : undefined
                        }
                    />
                    {apiKeyError ? (
                        <p className="text-xs text-danger mt-1">{apiKeyError}</p>
                    ) : apiKey.length > 0 ? (
                        <KeyValidationStatus
                            result={preValidationResult}
                            isValidating={preValidationResultLoading}
                            provider={keyToEdit.provider}
                            suppressError={endpointErrorField === 'endpoint'}
                            usesFoundry={isFoundryEdit}
                        />
                    ) : (
                        <p className="text-xs text-muted mt-1">
                            {isSystemOne && endpointChanged
                                ? 'The saved key will not be sent to the new endpoint. Enter its bearer token, or leave empty for no authentication.'
                                : (apiKeyRequiredReason ?? 'Leave empty to keep the current key')}
                        </p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}

function DeleteKeyModal({
    keyToDelete,
    dependentConfigs,
    dependentConfigsLoading,
    restrictionReason,
}: {
    keyToDelete: LLMProviderKey
    dependentConfigs: DependentConfigsResponse | null
    dependentConfigsLoading: boolean
    restrictionReason: string | null
}): JSX.Element {
    const { providerKeysLoading } = useValues(llmProviderKeysLogic)
    const { setKeyToDelete, confirmDelete } = useActions(llmProviderKeysLogic)
    const [replacementKeyId, setReplacementKeyId] = useState<string | undefined>(undefined)

    const hasEvaluations = (dependentConfigs?.evaluations.length ?? 0) > 0
    const hasAlternatives = (dependentConfigs?.alternative_keys.length ?? 0) > 0

    const firstAlternativeKeyId = dependentConfigs?.alternative_keys[0]?.id
    useEffect(() => {
        if (hasAlternatives && firstAlternativeKeyId) {
            setReplacementKeyId(firstAlternativeKeyId)
        }
    }, [hasAlternatives, firstAlternativeKeyId])

    const handleClose = (): void => {
        setKeyToDelete(null)
    }

    const handleDelete = (): void => {
        confirmDelete(hasEvaluations && hasAlternatives ? replacementKeyId : undefined)
    }

    const replacementOptions =
        dependentConfigs?.alternative_keys.map((key: AlternativeKey) => ({
            value: key.id,
            label: key.name,
        })) ?? []

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Delete API key?"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={handleDelete}
                        loading={providerKeysLoading}
                        disabled={dependentConfigsLoading}
                        disabledReason={restrictionReason}
                    >
                        Delete key
                    </LemonButton>
                </>
            }
        >
            {dependentConfigsLoading ? (
                <LemonSkeleton className="h-20" />
            ) : (
                <div className="space-y-4">
                    <p>
                        Are you sure you want to delete "<strong>{keyToDelete.name}</strong>"? This cannot be undone.
                    </p>

                    {hasEvaluations && (
                        <div className="bg-bg-light border rounded p-3">
                            <p className="font-medium mb-2">
                                {dependentConfigs!.evaluations.length} evaluation
                                {dependentConfigs!.evaluations.length === 1 ? '' : 's'} using this key:
                            </p>
                            <ul className="list-disc pl-4 text-sm text-muted space-y-1">
                                {dependentConfigs!.evaluations.map((evaluation) => (
                                    <li key={evaluation.id}>{evaluation.name}</li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {hasEvaluations && hasAlternatives && (
                        <div>
                            <label className="text-sm font-medium">Replace with another key</label>
                            <LemonSelect
                                value={replacementKeyId}
                                onChange={setReplacementKeyId}
                                options={replacementOptions}
                                className="mt-1"
                                fullWidth
                            />
                            <p className="text-xs text-muted mt-1">
                                The selected key will be used by evaluations that currently use this key.
                            </p>
                        </div>
                    )}

                    {hasEvaluations && !hasAlternatives && (
                        <div className="bg-warning-highlight border border-warning rounded p-3">
                            <p className="text-sm">
                                <strong>No replacement keys available.</strong> These evaluations will be disabled after
                                deletion.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </LemonModal>
    )
}

export function LLMProviderKeysSettings(): JSX.Element {
    const {
        providerKeys,
        providerKeysLoading,
        evaluationConfigLoading,
        editingKey,
        validatingKeyId,
        keyToDelete,
        dependentConfigs,
        dependentConfigsLoading,
    } = useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, validateProviderKey, setEditingKey, setKeyToDelete } = useActions(llmProviderKeysLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const columns: LemonTableColumns<LLMProviderKey> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, key) => (
                <div className="flex items-center gap-2">
                    <IconKey className="text-muted" />
                    <div>
                        <span className="font-medium">{key.name}</span>
                        {key.error_message && (key.state === 'invalid' || key.state === 'error') && (
                            <div className="text-xs text-danger mt-0.5">{key.error_message}</div>
                        )}
                    </div>
                </div>
            ),
        },
        {
            title: 'Provider',
            key: 'provider',
            render: (_, key) => (
                <div className="flex items-center gap-1.5">
                    <LLMProviderIcon provider={key.provider} />
                    <span>{LLM_PROVIDER_LABELS[key.provider]}</span>
                </div>
            ),
        },
        {
            title: 'Key',
            key: 'api_key_masked',
            render: (_, key) => <code className="text-sm bg-bg-light px-2 py-1 rounded">{key.api_key_masked}</code>,
        },
        {
            title: 'State',
            key: 'state',
            render: (_, key) => <StateTag state={key.state} errorMessage={key.error_message} />,
        },
        {
            title: 'Last used',
            key: 'last_used_at',
            render: (_, key) => <span className="text-muted text-sm">{formatDate(key.last_used_at)}</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, key) => (
                <div className="text-sm">
                    <div>{formatDate(key.created_at)}</div>
                    {key.created_by && (
                        <div className="text-muted text-xs">by {key.created_by.first_name || key.created_by.email}</div>
                    )}
                </div>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 150,
            render: (_, key) => (
                <div className="flex gap-1">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={validatingKeyId === key.id}
                        onClick={() => validateProviderKey({ id: key.id })}
                        disabledReason={restrictionReason}
                    >
                        Validate
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => setEditingKey(key)}
                        disabledReason={restrictionReason}
                    >
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => setKeyToDelete(key)}
                        disabledReason={restrictionReason}
                    />
                </div>
            ),
        },
    ]

    const isLoading = (providerKeysLoading || evaluationConfigLoading) && providerKeys.length === 0

    return (
        <>
            <div className="space-y-6">
                {isLoading ? (
                    <LemonSkeleton className="w-full h-64" />
                ) : (
                    <>
                        {restrictionReason && (
                            <LemonBanner type="info">
                                {restrictionReason} Ask a project admin to add or manage API keys on your behalf.
                            </LemonBanner>
                        )}

                        {providerKeys.length > 0 && (
                            <div className="flex justify-between items-start">
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => setNewKeyModalOpen(true)}
                                    disabledReason={restrictionReason}
                                >
                                    Add API key
                                </LemonButton>
                            </div>
                        )}

                        {providerKeys.length === 0 ? (
                            <div className="border rounded-lg p-8 flex flex-col items-center">
                                <IconKey className="text-muted text-4xl mb-4" />
                                <h3 className="font-semibold mb-2">No API keys configured</h3>
                                <p className="text-muted mb-4 text-center">
                                    {restrictionReason ? (
                                        <>
                                            Only project admins can add API keys for AI observability.
                                            <br />
                                            Ask a project admin to add a key for evaluations and the playground.
                                        </>
                                    ) : (
                                        <>
                                            Add your API key for AI observability features with your own account.
                                            <br />
                                            Used for evaluations and the playground.
                                        </>
                                    )}
                                </p>
                                {!restrictionReason && (
                                    <LemonButton
                                        type="primary"
                                        icon={<IconPlus />}
                                        onClick={() => setNewKeyModalOpen(true)}
                                    >
                                        Add API key
                                    </LemonButton>
                                )}
                            </div>
                        ) : (
                            <LemonTable
                                columns={columns}
                                dataSource={sortProviderKeys(providerKeys)}
                                loading={providerKeysLoading}
                                rowKey="id"
                            />
                        )}
                    </>
                )}
            </div>
            <AddKeyModal restrictionReason={restrictionReason} />
            {editingKey && <EditKeyModal keyToEdit={editingKey} restrictionReason={restrictionReason} />}
            {keyToDelete && (
                <DeleteKeyModal
                    keyToDelete={keyToDelete}
                    dependentConfigs={dependentConfigs}
                    dependentConfigsLoading={dependentConfigsLoading}
                    restrictionReason={restrictionReason}
                />
            )}
        </>
    )
}
