import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { trustedRelaySenderSaveState } from '../TrustedRelaySenderSettings/trustedRelaySenderSaveState'
import { TrustedRelaySenderSettingsProps } from '../TrustedRelaySenderSettings/TrustedRelaySenderSettings'

export function QuillTrustedRelaySenderSettings({
    configId,
    value,
    savedValue,
    restrictionReason,
    savingConfigId,
    onChange,
    onSave,
}: TrustedRelaySenderSettingsProps): JSX.Element {
    const { isSaving, isSavingAny, disabledReason } = trustedRelaySenderSaveState({
        configId,
        value,
        savedValue,
        restrictionReason,
        savingConfigId,
    })
    const inputId = `trusted-relay-sender-${configId}`

    return (
        <Field>
            <FieldLabel htmlFor={inputId}>Trusted relay sender</FieldLabel>
            <FieldDescription>
                Enter the exact From address used by your email relay. PostHog will identify the customer from
                X-PostHog-Requester or Reply-To only for authenticated email from this address. Clear the field to
                disable this behavior.
            </FieldDescription>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    id={inputId}
                    className="min-w-60 flex-1"
                    type="email"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder="no-reply@example.com"
                    disabledReason={restrictionReason}
                    disabled={isSavingAny}
                />
                <Button
                    variant="outline"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="trusted-relay-sender-save"
                    disabledReason={disabledReason}
                >
                    Save relay sender
                </Button>
            </div>
        </Field>
    )
}
