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
    Text,
} from '@posthog/quill'

import { LLMProviderIcon } from '../LLMProviderIcon'
import { FoundryEndpointField } from './FoundryEndpointField'
import { KeyValidationStatus } from './KeyValidationStatus'
import {
    DEFAULT_AZURE_API_VERSION,
    KeyValidationResult,
    LLMProvider,
    LLM_PROVIDER_LABELS,
} from './llmProviderKeysLogic'
import { SystemOneConnectionFields } from './SystemOneConnectionFields'

function QuillTextField({
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
    const id = useId()

    return (
        <Field data-invalid={!!error || undefined}>
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <Input
                id={id}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={placeholder}
                aria-invalid={!!error || undefined}
            />
            {error && <FieldError>{error}</FieldError>}
        </Field>
    )
}

export interface QuillEditKeyDialogProps {
    onClose: () => void
    onSubmit: () => void
    submitLoading: boolean
    submitDisabled: boolean
    disabledReason: string | null
    provider: LLMProvider
    isAzureEdit: boolean
    isFoundryEdit: boolean
    isSystemOne: boolean
    isOpenAICompatibleEdit: boolean
    azureEndpoint: string
    onAzureEndpointChange: (value: string) => void
    azureEndpointError: string | null
    onFoundryEndpointChange: (value: string) => void
    foundryEndpointError: string | null
    apiVersion: string
    onApiVersionChange: (value: string) => void
    apiVersionError: string | null
    baseUrl: string
    onBaseUrlChange: (value: string) => void
    baseUrlError: string | null
    name: string
    onNameChange: (value: string) => void
    nameError: string | null
    apiKey: string
    onApiKeyChange: (value: string) => void
    onApiKeyBlur: () => void
    apiKeyPlaceholder: string
    apiKeyInvalid: boolean
    apiKeyError: string | null
    apiKeyHint: string
    suppressValidationError: boolean
    preValidationResult: KeyValidationResult | null
    preValidationResultLoading: boolean
}

export function QuillEditKeyDialog({
    onClose,
    onSubmit,
    submitLoading,
    submitDisabled,
    disabledReason,
    provider,
    isAzureEdit,
    isFoundryEdit,
    isSystemOne,
    isOpenAICompatibleEdit,
    azureEndpoint,
    onAzureEndpointChange,
    azureEndpointError,
    onFoundryEndpointChange,
    foundryEndpointError,
    apiVersion,
    onApiVersionChange,
    apiVersionError,
    baseUrl,
    onBaseUrlChange,
    baseUrlError,
    name,
    onNameChange,
    nameError,
    apiKey,
    onApiKeyChange,
    onApiKeyBlur,
    apiKeyPlaceholder,
    apiKeyInvalid,
    apiKeyError,
    apiKeyHint,
    suppressValidationError,
    preValidationResult,
    preValidationResultLoading,
}: QuillEditKeyDialogProps): JSX.Element {
    const apiKeyId = useId()

    return (
        <Dialog open onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Edit API key</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <Text size="xs" weight="medium" render={<span className="m-0" />}>
                                Provider
                            </Text>
                            <Text size="xs" render={<span className="m-0 flex items-center gap-1.5" />}>
                                <LLMProviderIcon provider={provider} />
                                <span>{LLM_PROVIDER_LABELS[provider]}</span>
                            </Text>
                        </Field>
                        {isAzureEdit && (
                            <>
                                <QuillTextField
                                    label="Azure endpoint"
                                    value={azureEndpoint}
                                    onChange={onAzureEndpointChange}
                                    placeholder="https://my-resource.openai.azure.com/"
                                    error={azureEndpointError}
                                />
                                <QuillTextField
                                    label="API version"
                                    value={apiVersion}
                                    onChange={onApiVersionChange}
                                    placeholder={DEFAULT_AZURE_API_VERSION}
                                    error={apiVersionError}
                                />
                            </>
                        )}
                        {isFoundryEdit && (
                            <FoundryEndpointField
                                optional={false}
                                value={azureEndpoint}
                                onChange={onFoundryEndpointChange}
                                errorMessage={foundryEndpointError}
                            />
                        )}
                        {isSystemOne && <SystemOneConnectionFields />}
                        {isOpenAICompatibleEdit && (
                            <QuillTextField
                                label="Base URL"
                                value={baseUrl}
                                onChange={onBaseUrlChange}
                                placeholder="https://api.example.com/v1"
                                error={baseUrlError}
                            />
                        )}
                        <QuillTextField label="Name" value={name} onChange={onNameChange} error={nameError} />
                        <Field data-invalid={apiKeyInvalid || undefined}>
                            <FieldLabel htmlFor={apiKeyId}>API key</FieldLabel>
                            <Input
                                id={apiKeyId}
                                value={apiKey}
                                onChange={(event) => onApiKeyChange(event.target.value)}
                                onBlur={onApiKeyBlur}
                                placeholder={apiKeyPlaceholder}
                                type="password"
                                autoComplete="off"
                                aria-invalid={apiKeyInvalid || undefined}
                            />
                            {apiKeyError ? (
                                <FieldError>{apiKeyError}</FieldError>
                            ) : apiKey.length > 0 ? (
                                <KeyValidationStatus
                                    result={preValidationResult}
                                    isValidating={preValidationResultLoading}
                                    provider={provider}
                                    suppressError={suppressValidationError}
                                    usesFoundry={isFoundryEdit}
                                />
                            ) : (
                                <FieldDescription>{apiKeyHint}</FieldDescription>
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
                        disabledReason={disabledReason}
                    >
                        Save changes
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
