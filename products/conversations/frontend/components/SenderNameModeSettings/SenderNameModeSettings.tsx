import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import type { EmailSenderNameMode } from '../../scenes/settings/supportSettingsLogic'
import {
    SENDER_NAME_MODE_OPTIONS,
    senderNameModeDescription,
    senderNameModeDisabledReason,
} from './senderNameModeOptions'

export interface SenderNameModeSettingsProps {
    configId: string
    value: EmailSenderNameMode
    displayName: string
    restrictionReason?: string | null
    savingConfigId: string | null
    onChange: (mode: EmailSenderNameMode) => void
}

export function SenderNameModeSettings({
    configId,
    value,
    displayName,
    restrictionReason,
    savingConfigId,
    onChange,
}: SenderNameModeSettingsProps): JSX.Element {
    return (
        <div>
            <LemonLabel htmlFor={`email-sender-name-mode-${configId}`}>Sender name</LemonLabel>
            <p className="text-xs text-muted-alt mb-2">{senderNameModeDescription(value, displayName)}</p>
            <LemonSelect<EmailSenderNameMode>
                id={`email-sender-name-mode-${configId}`}
                size="small"
                value={value}
                options={SENDER_NAME_MODE_OPTIONS}
                onChange={onChange}
                loading={savingConfigId === configId}
                disabledReason={senderNameModeDisabledReason(restrictionReason, savingConfigId !== null)}
                data-attr="email-sender-name-mode-select"
            />
        </div>
    )
}
