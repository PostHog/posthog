import { useValues } from 'kea'
import { useId } from 'react'

import { Button, Field, FieldLabel, Input } from '@posthog/quill'

import { passkeySettingsLogic } from './passkeySettingsLogic'
import { QuillPasskeyRegistrationBanners } from './QuillPasskeyRegistrationBanners'

export function QuillPasskeyAddForm({
    label,
    onLabelChange,
    isRegistering,
    onAddPasskey,
}: {
    label: string
    onLabelChange: (label: string) => void
    isRegistering: boolean
    onAddPasskey: () => void
}): JSX.Element {
    const { registrationStep } = useValues(passkeySettingsLogic)
    const inputId = useId()

    return (
        <div className="flex flex-col gap-4">
            <QuillPasskeyRegistrationBanners />
            <div className="flex flex-wrap items-end gap-2">
                <Field className="min-w-60 flex-1">
                    <FieldLabel htmlFor={inputId}>Add a new passkey</FieldLabel>
                    <Input
                        id={inputId}
                        size="sm"
                        placeholder="Passkey name (optional)"
                        value={label}
                        onChange={(event) => onLabelChange(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                onAddPasskey()
                            }
                        }}
                        disabled={isRegistering}
                        maxLength={200}
                    />
                </Field>
                <Button
                    variant="primary"
                    onClick={onAddPasskey}
                    loading={isRegistering}
                    disabledReason={isRegistering ? 'Registration in progress...' : undefined}
                >
                    {registrationStep === 'verifying' ? 'Verifying...' : 'Add passkey'}
                </Button>
            </div>
        </div>
    )
}
