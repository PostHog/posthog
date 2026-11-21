import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { EmailConfigStatus } from './supportSettingsLogic'

export interface DnsRecord {
    record_type: string
    name: string
    value: string
    valid: string
}

export function defaultEmailDisabledReason(
    adminRestrictionReason: string | null | undefined,
    config: EmailConfigStatus,
    isSettingAnyDefault: boolean
): string | undefined {
    if (adminRestrictionReason) {
        return adminRestrictionReason
    }
    if (config.is_default) {
        return 'This is already the primary email address'
    }
    if (isSettingAnyDefault) {
        return 'Updating the primary address…'
    }
    return undefined
}

export function trustedRelaySenderValue(
    config: EmailConfigStatus,
    trustedRelaySenderDrafts: Record<string, string>
): string {
    return trustedRelaySenderDrafts[config.id] ?? config.trusted_relay_sender ?? ''
}

export function confirmDisconnectEmail(config: EmailConfigStatus, disconnectEmail: (configId: string) => void): void {
    LemonDialog.open({
        title: `Disconnect ${config.from_email}?`,
        description:
            'This will stop creating tickets from this email and may remove the sending domain. Existing tickets will not be affected.',
        primaryButton: {
            status: 'danger',
            children: 'Disconnect',
            onClick: () => disconnectEmail(config.id),
        },
        secondaryButton: { children: 'Cancel' },
    })
}
