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

import { confirmDisconnectEmail, defaultEmailDisabledReason } from '../../scenes/settings/emailSettingsHelpers'
import { EmailConfigStatus } from '../../scenes/settings/supportSettingsLogic'
import { useEmailConfigContent } from '../../scenes/settings/useEmailConfigContent'
import { QuillDnsRecordsTable } from '../QuillDnsRecordsTable/QuillDnsRecordsTable'
import { QuillEmailDisplayNameSettings } from '../QuillEmailDisplayNameSettings/QuillEmailDisplayNameSettings'
import { QuillEmailForwardingAddress } from '../QuillEmailForwardingAddress/QuillEmailForwardingAddress'
import { QuillTrustedRelaySenderSettings } from '../QuillTrustedRelaySenderSettings/QuillTrustedRelaySenderSettings'

export function QuillEmailConfigContent({ config }: { config: EmailConfigStatus }): JSX.Element {
    const email = useEmailConfigContent(config)

    return (
        <div className="flex flex-col gap-3">
            {config.forwarding_address && <QuillEmailForwardingAddress forwardingAddress={config.forwarding_address} />}

            <QuillEmailDisplayNameSettings
                configId={config.id}
                value={email.displayName}
                savedValue={config.from_name}
                restrictionReason={email.adminRestrictionReason}
                savingConfigId={email.emailDisplayNameSavingConfigId}
                onChange={email.setDisplayNameDraft}
                onSave={email.saveDisplayName}
            />

            <Separator />

            <Field>
                <FieldLabel>Domain verification</FieldLabel>
                <FieldDescription>Add DNS records to enable outbound sending (SPF/DKIM).</FieldDescription>

                <QuillDnsRecordsTable records={email.sendingRecords} />

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
                        onClick={email.verifyEmail}
                        loading={email.isVerifying}
                        disabledReason={email.adminRestrictionReason}
                    >
                        <IconRefresh />
                        {config.domain_verified ? 'Re-verify' : 'Verify domain'}
                    </Button>

                    {config.domain_verified && (
                        <Button variant="outline" onClick={email.sendTestEmail} loading={email.isTesting}>
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
                        value={email.trustedRelaySender}
                        savedValue={config.trusted_relay_sender}
                        restrictionReason={email.adminRestrictionReason}
                        savingConfigId={email.trustedRelaySavingConfigId}
                        onChange={email.setTrustedRelaySenderDraft}
                        onSave={email.saveTrustedRelaySender}
                    />
                </>
            )}

            <Separator />

            <div className="flex flex-wrap items-center justify-between gap-2">
                <Button
                    variant="outline"
                    loading={email.isSettingDefault}
                    disabledReason={defaultEmailDisabledReason(
                        email.adminRestrictionReason,
                        config,
                        email.isSettingAnyDefault
                    )}
                    tooltip="Tickets opened from the widget are sent from the primary address"
                    onClick={email.setDefaultEmail}
                >
                    {config.is_default ? 'Primary address' : 'Set as primary'}
                </Button>
                <Button
                    variant="destructive-outline"
                    disabledReason={email.adminRestrictionReason}
                    onClick={() => confirmDisconnectEmail(config, email.disconnectEmail)}
                >
                    Disconnect
                </Button>
            </div>
        </div>
    )
}
