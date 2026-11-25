import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { LLM_PROVIDER_SELECT_OPTIONS } from '../LLMProviderIcon'
import { FoundryEndpointField } from './FoundryEndpointField'
import { KeyValidationStatus } from './KeyValidationStatus'
import { DEFAULT_AZURE_API_VERSION, KeyValidationResult, LLMProvider } from './llmProviderKeysLogic'
import { SystemOneConnectionFields } from './SystemOneConnectionFields'

const PROVIDER_ITEMS = LLM_PROVIDER_SELECT_OPTIONS.map((option) => ({
    value: option.value,
    label: (
        <span className="flex items-center gap-2">
            {option.icon}
            {option.label}
        </span>
    ),
}))

export interface QuillAddKeyDialogProps {
    open: boolean
    onClose: () => void
    onSubmit: () => void
    submitLoading: boolean
    submitDisabled: boolean
    restrictionReason: string | null
    providerKeysLoading: boolean
    provider: LLMProvider
    onProviderChange: (provider: LLMProvider) => void
    isAzure: boolean
    isAnthropic: boolean
    isSystemOne: boolean
    isOpenAICompatible: boolean
    azureEndpoint: string
    onAzureEndpointChange: (value: string) => void
    onFoundryEndpointChange: (value: string) => void
    apiVersion: string
    onApiVersionChange: (value: string) => void
    baseUrl: string
    onBaseUrlChange: (value: string) => void
    name: string
    onNameChange: (value: string) => void
    apiKey: string
    onApiKeyChange: (value: string) => void
    onApiKeyBlur: () => void
    apiKeyPlaceholder: string
    apiKeyInvalid: boolean
    usesFoundry: boolean
    endpointErrorField: 'endpoint' | 'key' | null
    preValidationResult: KeyValidationResult | null
    preValidationResultLoading: boolean
}

export function QuillAddKeyDialog({
    open,
    onClose,
    onSubmit,
    submitLoading,
    submitDisabled,
    restrictionReason,
    providerKeysLoading,
    provider,
    onProviderChange,
    isAzure,
    isAnthropic,
    isSystemOne,
    isOpenAICompatible,
    azureEndpoint,
    onAzureEndpointChange,
    onFoundryEndpointChange,
    apiVersion,
    onApiVersionChange,
    baseUrl,
    onBaseUrlChange,
    name,
    onNameChange,
    apiKey,
    onApiKeyChange,
    onApiKeyBlur,
    apiKeyPlaceholder,
    apiKeyInvalid,
    usesFoundry,
    endpointErrorField,
    preValidationResult,
    preValidationResultLoading,
}: QuillAddKeyDialogProps): JSX.Element {
    const id = useId()
    const endpointInvalid = endpointErrorField === 'endpoint'

    return (
        <Dialog open={open} onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add API key</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor={`${id}-provider`}>Provider</FieldLabel>
                            <Select
                                items={PROVIDER_ITEMS}
                                value={provider}
                                onValueChange={(value) => onProviderChange(value as LLMProvider)}
                                disabled={providerKeysLoading}
                            >
                                <SelectTrigger id={`${id}-provider`} className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {PROVIDER_ITEMS.map((item) => (
                                        <SelectItem key={item.value} value={item.value}>
                                            {item.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        {isAzure && (
                            <>
                                <Field data-invalid={endpointInvalid || undefined}>
                                    <FieldLabel htmlFor={`${id}-azure-endpoint`}>Azure endpoint</FieldLabel>
                                    <Input
                                        id={`${id}-azure-endpoint`}
                                        value={azureEndpoint}
                                        onChange={(event) => onAzureEndpointChange(event.target.value)}
                                        placeholder="https://my-resource.openai.azure.com/"
                                        aria-invalid={endpointInvalid || undefined}
                                    />
                                    {endpointInvalid ? (
                                        <FieldError>
                                            {preValidationResult?.error_message || 'Invalid Azure endpoint'}
                                        </FieldError>
                                    ) : (
                                        <FieldDescription>
                                            The endpoint URL of your Azure OpenAI resource
                                        </FieldDescription>
                                    )}
                                </Field>
                                <Field>
                                    <FieldLabel htmlFor={`${id}-api-version`}>API version</FieldLabel>
                                    <Input
                                        id={`${id}-api-version`}
                                        value={apiVersion}
                                        onChange={(event) => onApiVersionChange(event.target.value)}
                                        placeholder={DEFAULT_AZURE_API_VERSION}
                                    />
                                    <FieldDescription>
                                        Azure OpenAI API version (defaults to {DEFAULT_AZURE_API_VERSION})
                                    </FieldDescription>
                                </Field>
                            </>
                        )}
                        {isAnthropic && (
                            <FoundryEndpointField
                                optional
                                value={azureEndpoint}
                                onChange={onFoundryEndpointChange}
                                errorMessage={
                                    endpointInvalid
                                        ? preValidationResult?.error_message || 'Invalid Microsoft Foundry endpoint'
                                        : null
                                }
                            />
                        )}
                        {isSystemOne && <SystemOneConnectionFields />}
                        {isOpenAICompatible && (
                            <Field data-invalid={endpointInvalid || undefined}>
                                <FieldLabel htmlFor={`${id}-base-url`}>Base URL</FieldLabel>
                                <Input
                                    id={`${id}-base-url`}
                                    value={baseUrl}
                                    onChange={(event) => onBaseUrlChange(event.target.value)}
                                    placeholder="https://api.example.com/v1"
                                    aria-invalid={endpointInvalid || undefined}
                                />
                                {endpointInvalid ? (
                                    <FieldError>{preValidationResult?.error_message || 'Invalid base URL'}</FieldError>
                                ) : (
                                    <FieldDescription>
                                        The base URL of your OpenAI-compatible API. Must be a public https:// URL that
                                        serves the /models and /chat/completions endpoints.
                                    </FieldDescription>
                                )}
                            </Field>
                        )}
                        <Field>
                            <FieldLabel htmlFor={`${id}-name`}>Name</FieldLabel>
                            <Input
                                id={`${id}-name`}
                                value={name}
                                onChange={(event) => onNameChange(event.target.value)}
                                placeholder="e.g. Production key"
                            />
                            <FieldDescription>A friendly name to identify this key</FieldDescription>
                        </Field>
                        <Field data-invalid={apiKeyInvalid || undefined}>
                            <FieldLabel htmlFor={`${id}-api-key`}>API key</FieldLabel>
                            <Input
                                id={`${id}-api-key`}
                                value={apiKey}
                                onChange={(event) => onApiKeyChange(event.target.value)}
                                onBlur={onApiKeyBlur}
                                placeholder={apiKeyPlaceholder}
                                type="password"
                                autoComplete="off"
                                aria-invalid={apiKeyInvalid || undefined}
                            />
                            <KeyValidationStatus
                                result={preValidationResult}
                                isValidating={preValidationResultLoading}
                                provider={provider}
                                suppressError={endpointInvalid}
                                usesFoundry={usesFoundry}
                            />
                            {isSystemOne && (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Sent as a bearer token. Leave empty only if your custom endpoint does not require
                                    authentication.
                                </Text>
                            )}
                        </Field>
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSubmit}
                        loading={submitLoading}
                        disabled={submitDisabled}
                        disabledReason={restrictionReason}
                    >
                        Add key
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
