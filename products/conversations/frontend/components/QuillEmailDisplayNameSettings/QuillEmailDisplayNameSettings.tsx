import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { emailDisplayNameSaveState } from '../EmailDisplayNameSettings/emailDisplayNameSaveState'
import { EmailDisplayNameSettingsProps } from '../EmailDisplayNameSettings/EmailDisplayNameSettings'

export function QuillEmailDisplayNameSettings({
    configId,
    value,
    savedValue,
    restrictionReason,
    savingConfigId,
    onChange,
    onSave,
}: EmailDisplayNameSettingsProps): JSX.Element {
    const { isSaving, isSavingAny, disabledReason } = emailDisplayNameSaveState({
        configId,
        value,
        savedValue,
        restrictionReason,
        savingConfigId,
    })
    const inputId = `email-display-name-${configId}`

    return (
        <Field>
            <FieldLabel htmlFor={inputId}>Display name</FieldLabel>
            <FieldDescription>Customers see this name as the sender of every reply.</FieldDescription>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    id={inputId}
                    className="min-w-60 flex-1"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder="Acme Support"
                    maxLength={255}
                    disabledReason={restrictionReason}
                    disabled={isSavingAny}
                />
                <Button
                    variant="outline"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="email-display-name-save"
                    disabledReason={disabledReason}
                >
                    Save display name
                </Button>
            </div>
        </Field>
    )
}
