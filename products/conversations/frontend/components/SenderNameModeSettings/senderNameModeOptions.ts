import type { EmailSenderNameMode } from '../../scenes/settings/supportSettingsLogic'

export interface SenderNameModeOption {
    value: EmailSenderNameMode
    label: string
}

export const SENDER_NAME_MODE_OPTIONS: SenderNameModeOption[] = [
    { value: 'channel', label: 'Display name' },
    { value: 'agent', label: "Agent's first name and display name" },
]

export function senderNameModeDescription(mode: EmailSenderNameMode, displayName: string): string {
    return mode === 'agent'
        ? `A reply from Sam shows as "Sam from ${displayName}". AI replies show as "${displayName}".`
        : `Every reply shows as "${displayName}".`
}

export function senderNameModeDisabledReason(
    restrictionReason: string | null | undefined,
    isSaving: boolean
): string | undefined {
    return restrictionReason ?? (isSaving ? 'Saving the sender name' : undefined)
}
