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
            <div className="text-xs text-muted-alt mb-2 space-y-1">
                <p className="m-0">
                    Enter the exact From address used by your email relay. For authenticated email from this address,
                    PostHog identifies the customer from the X-PostHog-Requester or Reply-To header. Your relay must add
                    one of these headers.
                </p>
                <p className="m-0">
                    A plain forward from a mailbox does not add them, so tickets show the mailbox as the customer. If
                    your routing keeps the original From address, you don't need a trusted relay sender. Clear the field
                    to turn this off.
                </p>
            </div>
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
