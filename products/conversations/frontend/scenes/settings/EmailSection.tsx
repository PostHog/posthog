import { useActions, useValues } from 'kea'

import { IconCopy, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonDivider, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function EmailSection(): JSX.Element {
    return (
        <SceneSection
            title="Email channel"
            description="Receive customer emails as support tickets and reply directly from PostHog. Set up forwarding and verify your domain to enable two-way email."
            className="mt-4"
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <EmailChannelSection />
            </LemonCard>
        </SceneSection>
    )
}

interface DnsRecord {
    record_type: string
    name: string
    value: string
    valid: string
}

function DnsRecordsTable({ records, title }: { records: DnsRecord[]; title: string }): JSX.Element | null {
    if (!records || records.length === 0) {
        return null
    }
    return (
        <div className="mt-2">
            <label className="font-medium text-sm">{title}</label>
            <div className="border rounded mt-1 overflow-x-auto">
                <table className="w-full text-xs">
                    <thead>
                        <tr className="bg-surface-primary">
                            <th className="text-left px-2 py-1">Type</th>
                            <th className="text-left px-2 py-1">Name</th>
                            <th className="text-left px-2 py-1">Value</th>
                            <th className="text-left px-2 py-1">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {records.map((record: DnsRecord, i: number) => (
                            <tr key={i} className="border-t">
                                <td className="px-2 py-1 font-mono">{record.record_type}</td>
                                <td className="px-2 py-1 font-mono break-all max-w-[200px]">{record.name}</td>
                                <td className="px-2 py-1 font-mono break-all max-w-[300px]">{record.value}</td>
                                <td className="px-2 py-1">
                                    {record.valid === 'valid' ? (
                                        <LemonTag type="success" size="small">
                                            Valid
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            Pending
                                        </LemonTag>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

function EmailChannelSection(): JSX.Element {
    const {
        emailConnected,
        emailFromEmail,
        emailFromName,
        emailConnecting,
        emailForwardingAddress,
        emailDomainVerified,
        emailDnsRecords,
        emailVerifying,
        emailSendingTest,
    } = useValues(supportSettingsLogic)
    const { setEmailFromEmail, setEmailFromName, connectEmail, disconnectEmail, verifyEmailDomain, sendTestEmail } =
        useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const sendingRecords = emailDnsRecords?.sending_dns_records as DnsRecord[] | undefined

    return (
        <div className="flex flex-col gap-y-2">
            {!emailConnected ? (
                <>
                    <div>
                        <label className="font-medium">Connect email</label>
                        <p className="text-xs text-muted-alt">
                            Enter the email address customers will contact you at (e.g. support@company.com). We'll give
                            you a forwarding address to set up in your email provider and register your domain for
                            outbound sending.
                        </p>
                    </div>
                    <div className="flex flex-col gap-2">
                        <LemonInput
                            value={emailFromEmail}
                            onChange={(value) => setEmailFromEmail(value)}
                            placeholder="support@company.com"
                            fullWidth
                        />
                        <LemonInput
                            value={emailFromName}
                            onChange={(value) => setEmailFromName(value)}
                            placeholder="Display name (e.g. Acme Support)"
                            fullWidth
                        />
                        <div>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={connectEmail}
                                loading={emailConnecting}
                                disabledReason={
                                    adminRestrictionReason ??
                                    (!emailFromEmail || !emailFromName
                                        ? 'Enter email address and display name'
                                        : undefined)
                                }
                            >
                                Connect email
                            </LemonButton>
                        </div>
                    </div>
                </>
            ) : (
                <>
                    <div className="flex items-center gap-2">
                        <label className="font-medium">Connection</label>
                        <LemonTag type="success">Connected</LemonTag>
                        {emailDomainVerified ? (
                            <LemonTag type="success">Domain verified</LemonTag>
                        ) : (
                            <LemonTag type="warning">Domain not verified</LemonTag>
                        )}
                    </div>
                    {emailFromEmail && (
                        <p className="text-xs text-muted-alt mt-0">
                            Sending as <strong>{emailFromName || emailFromEmail}</strong> ({emailFromEmail})
                        </p>
                    )}

                    {/* Forwarding address */}
                    {emailForwardingAddress && (
                        <>
                            <LemonDivider />
                            <div>
                                <label className="font-medium">Forwarding address</label>
                                <p className="text-xs text-muted-alt">
                                    Set up a forwarding rule in your email provider to forward incoming emails to this
                                    address.
                                </p>
                                <div className="flex items-center gap-2 mt-1">
                                    <code className="bg-surface-primary px-2 py-1 rounded text-sm break-all">
                                        {emailForwardingAddress}
                                    </code>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconCopy />}
                                        onClick={() => {
                                            void navigator.clipboard.writeText(emailForwardingAddress)
                                            lemonToast.success('Copied to clipboard')
                                        }}
                                    />
                                </div>
                            </div>
                            <LemonDivider />
                            <div>
                                <label className="font-medium">Setup instructions</label>
                                <div className="text-xs text-muted-alt mt-1 flex flex-col gap-1">
                                    <p className="mb-0">
                                        <strong>Gmail:</strong> Settings → Forwarding → Add a forwarding address → paste
                                        the address above → confirm.
                                    </p>
                                    <p className="mb-0">
                                        <strong>Outlook:</strong> Settings → Mail → Forwarding → Enable forwarding →
                                        paste the address above.
                                    </p>
                                    <p className="mb-0">
                                        <strong>Other:</strong> Set up a forwarding rule to send all incoming emails to
                                        the address above.
                                    </p>
                                </div>
                            </div>
                        </>
                    )}

                    {/* Domain verification */}
                    <LemonDivider />
                    <div>
                        <label className="font-medium">Domain verification</label>
                        <p className="text-xs text-muted-alt">
                            Add these DNS records to your domain to enable outbound email sending. This ensures your
                            replies don't land in spam.
                        </p>

                        {sendingRecords && sendingRecords.length > 0 && (
                            <DnsRecordsTable records={sendingRecords} title="Sending records (SPF/DKIM)" />
                        )}

                        {!emailDomainVerified && (
                            <LemonBanner type="info" className="mt-2">
                                Add the DNS records above to your domain provider, then click "Verify domain" to check.
                            </LemonBanner>
                        )}

                        <div className="flex gap-2 mt-2">
                            <LemonButton
                                type={emailDomainVerified ? 'secondary' : 'primary'}
                                size="small"
                                onClick={verifyEmailDomain}
                                loading={emailVerifying}
                                icon={<IconRefresh />}
                            >
                                {emailDomainVerified ? 'Re-verify domain' : 'Verify domain'}
                            </LemonButton>

                            {emailDomainVerified && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={sendTestEmail}
                                    loading={emailSendingTest}
                                >
                                    Send test email
                                </LemonButton>
                            )}
                        </div>
                    </div>

                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            disabledReason={adminRestrictionReason}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Disconnect email?',
                                    description:
                                        'This will stop creating tickets from emails and remove the sending domain. Existing tickets will not be affected.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Disconnect',
                                        onClick: disconnectEmail,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Disconnect email
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
