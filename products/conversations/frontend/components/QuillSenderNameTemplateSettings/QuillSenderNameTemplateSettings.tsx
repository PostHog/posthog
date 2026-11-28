import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import {
    SENDER_NAME_AUTHOR_PLACEHOLDER,
    senderNameTemplateSaveState,
} from '../SenderNameTemplateSettings/senderNameTemplateSaveState'
import { SenderNameTemplateSettingsProps } from '../SenderNameTemplateSettings/SenderNameTemplateSettings'

export function QuillSenderNameTemplateSettings({
    configId,
    value,
    savedValue,
    displayName,
    restrictionReason,
    savingConfigId,
    onChange,
    onSave,
}: SenderNameTemplateSettingsProps): JSX.Element {
    const { isSaving, isSavingAny, disabledReason, description } = senderNameTemplateSaveState({
        configId,
        value,
        savedValue,
        displayName,
        restrictionReason,
        savingConfigId,
    })
    const inputId = `email-sender-name-template-${configId}`

    return (
        <Field>
            <FieldLabel htmlFor={inputId}>Sender name for agent replies</FieldLabel>
            <FieldDescription>{description}</FieldDescription>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    id={inputId}
                    className="min-w-60 flex-1"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder={`${SENDER_NAME_AUTHOR_PLACEHOLDER} at Acme`}
                    maxLength={255}
                    disabledReason={restrictionReason}
                    disabled={isSavingAny}
                />
                <Button
                    variant="outline"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="email-sender-name-template-save"
                    disabledReason={disabledReason}
                >
                    Save sender name
                </Button>
            </div>
        </Field>
    )
}
