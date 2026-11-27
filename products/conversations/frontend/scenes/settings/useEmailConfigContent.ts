import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { DnsRecord, trustedRelaySenderValue } from './emailSettingsHelpers'
import { EmailConfigStatus, supportSettingsLogic } from './supportSettingsLogic'

export interface EmailConfigContent {
    adminRestrictionReason: string | null
    sendingRecords: DnsRecord[]
    isVerifying: boolean
    isTesting: boolean
    isSettingDefault: boolean
    isSettingAnyDefault: boolean
    trustedRelaySender: string
    trustedRelaySavingConfigId: string | null
    displayName: string
    emailDisplayNameSavingConfigId: string | null
    senderNameTemplate: string
    emailSenderNameTemplateSavingConfigId: string | null
    verifyEmail: () => void
    sendTestEmail: () => void
    setDefaultEmail: () => void
    disconnectEmail: (configId: string) => void
    setTrustedRelaySenderDraft: (value: string) => void
    saveTrustedRelaySender: () => void
    setDisplayNameDraft: (value: string) => void
    saveDisplayName: () => void
    setSenderNameTemplateDraft: (value: string) => void
    saveSenderNameTemplate: () => void
}

export function useEmailConfigContent(config: EmailConfigStatus): EmailConfigContent {
    const {
        emailVerifyingConfigId,
        emailTestingConfigId,
        settingDefaultEmailConfigId,
        trustedRelaySenderDrafts,
        trustedRelaySavingConfigId,
        emailDisplayNameDrafts,
        emailDisplayNameSavingConfigId,
        emailSenderNameTemplateDrafts,
        emailSenderNameTemplateSavingConfigId,
    } = useValues(supportSettingsLogic)
    const actions = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return {
        adminRestrictionReason,
        sendingRecords: (config.dns_records?.sending_dns_records as DnsRecord[] | undefined) ?? [],
        isVerifying: emailVerifyingConfigId === config.id,
        isTesting: emailTestingConfigId === config.id,
        isSettingDefault: settingDefaultEmailConfigId === config.id,
        isSettingAnyDefault: settingDefaultEmailConfigId !== null,
        trustedRelaySender: trustedRelaySenderValue(config, trustedRelaySenderDrafts),
        trustedRelaySavingConfigId,
        displayName: emailDisplayNameDrafts[config.id] ?? config.from_name,
        emailDisplayNameSavingConfigId,
        senderNameTemplate: emailSenderNameTemplateDrafts[config.id] ?? config.sender_name_template ?? '',
        emailSenderNameTemplateSavingConfigId,
        verifyEmail: () => actions.verifyEmailDomain(config.id),
        sendTestEmail: () => actions.sendTestEmail(config.id),
        setDefaultEmail: () => actions.setDefaultEmail(config.id),
        disconnectEmail: actions.disconnectEmail,
        setTrustedRelaySenderDraft: (value: string) => actions.setTrustedRelaySenderDraft(config.id, value),
        saveTrustedRelaySender: () => actions.saveTrustedRelaySender(config.id),
        setDisplayNameDraft: (value: string) => actions.setEmailDisplayNameDraft(config.id, value),
        saveDisplayName: () => actions.saveEmailDisplayName(config.id),
        setSenderNameTemplateDraft: (value: string) => actions.setEmailSenderNameTemplateDraft(config.id, value),
        saveSenderNameTemplate: () => actions.saveEmailSenderNameTemplate(config.id),
    }
}
