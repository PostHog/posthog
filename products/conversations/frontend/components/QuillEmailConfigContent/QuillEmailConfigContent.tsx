import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    Separator,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import {
    confirmDisconnectEmail,
    defaultEmailDisabledReason,
    DnsRecord,
    trustedRelaySenderValue,
} from '../../scenes/settings/emailSettingsHelpers'
import { EmailConfigStatus, supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillDnsRecordsTable } from '../QuillDnsRecordsTable/QuillDnsRecordsTable'
import { QuillEmailForwardingAddress } from '../QuillEmailForwardingAddress/QuillEmailForwardingAddress'
import { QuillTrustedRelaySenderSettings } from '../QuillTrustedRelaySenderSettings/QuillTrustedRelaySenderSettings'

export function QuillEmailConfigContent({ config }: { config: EmailConfigStatus }): JSX.Element {
    const {
        emailVerifyingConfigId,
        emailTestingConfigId,
        settingDefaultEmailConfigId,
        trustedRelaySenderDrafts,
        trustedRelaySavingConfigId,
    } = useValues(supportSettingsLogic)
    const {
        disconnectEmail,
        verifyEmailDomain,
        sendTestEmail,
        setDefaultEmail,
        setTrustedRelaySenderDraft,
        saveTrustedRelaySender,
    } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const sendingRecords = (config.dns_records?.sending_dns_records as DnsRecord[] | undefined) ?? []
    const isVerifying = emailVerifyingConfigId === config.id
    const isTesting = emailTestingConfigId === config.id
    const isSettingDefault = settingDefaultEmailConfigId === config.id
    const isSettingAnyDefault = settingDefaultEmailConfigId !== null
    const trustedRelaySender = trustedRelaySenderValue(config, trustedRelaySenderDrafts)

    return (
        <div className="flex flex-col gap-3">
            {config.forwarding_address && <QuillEmailForwardingAddress forwardingAddress={config.forwarding_address} />}

            <Field>
                <FieldLabel>Domain verification</FieldLabel>
                <FieldDescription>Add DNS records to enable outbound sending (SPF/DKIM).</FieldDescription>

                <QuillDnsRecordsTable records={sendingRecords} />

                {!config.domain_verified && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                Add the DNS records above, then click "Verify domain". If you already have an SPF record
                                (e.g. <code>v=spf1 include:someservice.com ~all</code>), don't create a second one —
                                merge them into a single record:{' '}
                                <code>v=spf1 include:someservice.com include:mailgun.org ~all</code>
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}

                <div className="flex flex-wrap gap-2">
                    <Button
                        variant={config.domain_verified ? 'outline' : 'primary'}
                        onClick={() => verifyEmailDomain(config.id)}
                        loading={isVerifying}
                        disabledReason={adminRestrictionReason}
                    >
                        <IconRefresh />
                        {config.domain_verified ? 'Re-verify' : 'Verify domain'}
                    </Button>

                    {config.domain_verified && (
                        <Button variant="outline" onClick={() => sendTestEmail(config.id)} loading={isTesting}>
                            Send test email
                        </Button>
                    )}
                </div>
            </Field>

            {config.trusted_relay_sender !== undefined && (
                <>
                    <Separator />
                    <QuillTrustedRelaySenderSettings
                        configId={config.id}
                        value={trustedRelaySender}
                        savedValue={config.trusted_relay_sender}
                        restrictionReason={adminRestrictionReason}
                        savingConfigId={trustedRelaySavingConfigId}
                        onChange={(value) => setTrustedRelaySenderDraft(config.id, value)}
                        onSave={() => saveTrustedRelaySender(config.id)}
                    />
                </>
            )}

            <Separator />

            <div className="flex flex-wrap items-center justify-between gap-2">
                <Button
                    variant="outline"
                    loading={isSettingDefault}
                    disabledReason={defaultEmailDisabledReason(adminRestrictionReason, config, isSettingAnyDefault)}
                    tooltip="Tickets opened from the widget are sent from the primary address"
                    onClick={() => setDefaultEmail(config.id)}
                >
                    {config.is_default ? 'Primary address' : 'Set as primary'}
                </Button>
                <Button
                    variant="destructive-outline"
                    disabledReason={adminRestrictionReason}
                    onClick={() => confirmDisconnectEmail(config, disconnectEmail)}
                >
                    Disconnect
                </Button>
            </div>
        </div>
    )
}
