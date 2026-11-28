import { LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { emailDisplayNameSaveState } from './emailDisplayNameSaveState'

export interface EmailDisplayNameSettingsProps {
    configId: string
    value: string
    savedValue: string
    restrictionReason?: string | null
    savingConfigId: string | null
    onChange: (value: string) => void
    onSave: () => void
}

export function EmailDisplayNameSettings({
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

    return (
        <div>
            <LemonLabel htmlFor={`email-display-name-${configId}`}>Display name</LemonLabel>
            <p className="text-xs text-muted-alt mb-2">Customers see this name as the sender of every reply.</p>
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    id={`email-display-name-${configId}`}
                    value={value}
                    onChange={onChange}
                    placeholder="Acme Support"
                    maxLength={255}
                    disabled={!!restrictionReason || isSavingAny}
                    fullWidth
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onSave}
                    loading={isSaving}
                    data-attr="email-display-name-save"
                    disabledReason={disabledReason}
                >
                    Save display name
                </LemonButton>
            </div>
        </div>
    )
}
