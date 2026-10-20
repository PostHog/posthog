import { LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

export interface TrustedRelaySenderSettingsProps {
    configId: string
    value: string
    savedValue: string
    restrictionReason?: string | null
    savingConfigId: string | null
    onChange: (value: string) => void
    onSave: () => void
}

export function TrustedRelaySenderSettings({
    configId,
    value,
    savedValue,
    restrictionReason,
    savingConfigId,
    onChange,
    onSave,
}: TrustedRelaySenderSettingsProps): JSX.Element {
    const isDirty = value.trim().toLowerCase() !== savedValue
    const isSaving = savingConfigId === configId
    const isSavingAny = savingConfigId !== null
    const disabledReason =
        restrictionReason ??
        (!isDirty ? 'No changes to save' : isSavingAny ? 'Saving a trusted relay sender' : undefined)

    return (
        <div className="border-t pt-3">
            <LemonLabel htmlFor={`trusted-relay-sender-${configId}`}>Trusted relay sender</LemonLabel>
            <p className="text-xs text-muted-alt mb-2">
                Enter the exact From address used by your email relay. PostHog will identify the customer from
                X-PostHog-Requester or Reply-To only for authenticated email from this address. Clear the field to
                disable this behavior.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    id={`trusted-relay-sender-${configId}`}
                    type="email"
                    value={value}
                    onChange={onChange}
                    placeholder="no-reply@example.com"
                    disabled={!!restrictionReason || isSavingAny}
                    fullWidth
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="trusted-relay-sender-save"
                    disabledReason={disabledReason}
                >
                    Save relay sender
                </LemonButton>
            </div>
        </div>
    )
}
