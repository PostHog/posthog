import { LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { SENDER_NAME_AUTHOR_PLACEHOLDER, senderNameTemplateSaveState } from './senderNameTemplateSaveState'

export interface SenderNameTemplateSettingsProps {
    configId: string
    value: string
    savedValue: string
    displayName: string
    restrictionReason?: string | null
    savingConfigId: string | null
    onChange: (value: string) => void
    onSave: () => void
}

export function SenderNameTemplateSettings({
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

    return (
        <div>
            <LemonLabel htmlFor={`email-sender-name-template-${configId}`}>Sender name for agent replies</LemonLabel>
            <p className="text-xs text-muted-alt mb-2">{description}</p>
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    id={`email-sender-name-template-${configId}`}
                    value={value}
                    onChange={onChange}
                    placeholder={`${SENDER_NAME_AUTHOR_PLACEHOLDER} at Acme`}
                    maxLength={255}
                    disabled={!!restrictionReason || isSavingAny}
                    fullWidth
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="email-sender-name-template-save"
                    disabledReason={disabledReason}
                >
                    Save sender name
                </LemonButton>
            </div>
        </div>
    )
}
