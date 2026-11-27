import {
    Field,
    FieldDescription,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type { EmailSenderNameMode } from '../../scenes/settings/supportSettingsLogic'
import {
    SENDER_NAME_MODE_OPTIONS,
    senderNameModeDescription,
    senderNameModeDisabledReason,
} from '../SenderNameModeSettings/senderNameModeOptions'
import { SenderNameModeSettingsProps } from '../SenderNameModeSettings/SenderNameModeSettings'

export function QuillSenderNameModeSettings({
    configId,
    value,
    displayName,
    restrictionReason,
    savingConfigId,
    onChange,
}: SenderNameModeSettingsProps): JSX.Element {
    const selectId = `email-sender-name-mode-${configId}`

    return (
        <Field>
            <FieldLabel htmlFor={selectId}>Sender name</FieldLabel>
            <FieldDescription>{senderNameModeDescription(value, displayName)}</FieldDescription>
            <Select<EmailSenderNameMode>
                items={SENDER_NAME_MODE_OPTIONS}
                value={value}
                onValueChange={(mode) => {
                    if (mode) {
                        onChange(mode)
                    }
                }}
            >
                <SelectTrigger
                    id={selectId}
                    className="w-fit"
                    data-attr="email-sender-name-mode-select"
                    disabledReason={senderNameModeDisabledReason(restrictionReason, savingConfigId !== null)}
                >
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {SENDER_NAME_MODE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </Field>
    )
}
