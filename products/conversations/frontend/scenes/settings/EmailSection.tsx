import { useActions, useValues } from 'kea'
import { type ChangeEvent, useState } from 'react'

import { IconPlus, IconRefresh } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    Input,
} from 'lib/ui/quill'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { EmailForwardingAddress } from '../../components/EmailForwardingAddress/EmailForwardingAddress'
import { EmailConfigStatus, supportSettingsLogic } from './supportSettingsLogic'

interface DnsRecord {
    record_type: string
    name: string
    value: string
    valid: string
}

function DnsRecordsTable({ records }: { records: DnsRecord[] }): JSX.Element | null {
    if (!records || records.length === 0) {
        return null
    }
    return (
        <div className="border rounded overflow-x-auto">
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
                                    <Badge variant="success">Valid</Badge>
                                ) : (
                                    <Badge variant="warning">Pending</Badge>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

function EmailConfigContent({ config }: { config: EmailConfigStatus }): JSX.Element {
    const { emailVerifyingConfigId, emailTestingConfigId, settingDefaultEmailConfigId } =
        useValues(supportSettingsLogic)
    const { disconnectEmail, verifyEmailDomain, sendTestEmail, setDefaultEmail } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const sendingRecords = config.dns_records?.sending_dns_records as DnsRecord[] | undefined
    const isVerifying = emailVerifyingConfigId === config.id
    const isTesting = emailTestingConfigId === config.id
    const isSettingDefault = settingDefaultEmailConfigId === config.id
    const isSettingAnyDefault = settingDefaultEmailConfigId !== null
    const primaryDisabledReason =
        adminRestrictionReason ??
        (config.is_default
            ? 'This is already the primary email address'
            : isSettingAnyDefault
              ? 'Updating the primary address…'
              : undefined)

    return (
        <div className="flex flex-col gap-3 p-3">
            {config.forwarding_address && <EmailForwardingAddress forwardingAddress={config.forwarding_address} />}

            {/* Domain verification */}
            <div>
                <label className="font-medium text-sm">Domain verification</label>
                <p className="text-xs text-muted-alt mb-1">Add DNS records to enable outbound sending (SPF/DKIM).</p>

                {sendingRecords && sendingRecords.length > 0 && <DnsRecordsTable records={sendingRecords} />}

                {!config.domain_verified && (
                    <div className="rounded border border-primary bg-surface-secondary p-2 text-sm mt-2">
                        Add the DNS records above, then click "Verify domain". If you already have an SPF record (e.g.{' '}
                        <code className="text-xs">v=spf1 include:someservice.com ~all</code>), don't create a second one
                        — merge them into a single record:{' '}
                        <code className="text-xs">v=spf1 include:someservice.com include:mailgun.org ~all</code>
                    </div>
                )}

                <div className="flex gap-2 mt-2">
                    <Button
                        variant={config.domain_verified ? 'outline' : 'primary'}
                        size="sm"
                        onClick={() => verifyEmailDomain(config.id)}
                        loading={isVerifying}
                        disabled={!!adminRestrictionReason}
                        title={adminRestrictionReason ?? undefined}
                    >
                        <IconRefresh />
                        {config.domain_verified ? 'Re-verify' : 'Verify domain'}
                    </Button>

                    {config.domain_verified && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => sendTestEmail(config.id)}
                            loading={isTesting}
                        >
                            Send test email
                        </Button>
                    )}
                </div>
            </div>

            {/* Default + disconnect */}
            <div className="flex justify-between items-center border-t pt-2">
                <Button
                    variant="outline"
                    size="sm"
                    loading={isSettingDefault}
                    disabled={!!primaryDisabledReason}
                    title={primaryDisabledReason ?? 'Tickets opened from the widget are sent from the primary address'}
                    onClick={() => setDefaultEmail(config.id)}
                >
                    {config.is_default ? 'Primary address' : 'Set as primary'}
                </Button>
                <AlertDialog>
                    <AlertDialogTrigger
                        render={
                            <Button
                                variant="outline"
                                size="sm"
                                disabled={!!adminRestrictionReason}
                                title={adminRestrictionReason ?? undefined}
                            />
                        }
                    >
                        Disconnect
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Disconnect {config.from_email}?</AlertDialogTitle>
                            <AlertDialogDescription>
                                This will stop creating tickets from this email and may remove the sending domain.
                                Existing tickets will not be affected.
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                            <AlertDialogClose
                                render={<Button variant="destructive" onClick={() => disconnectEmail(config.id)} />}
                            >
                                Disconnect
                            </AlertDialogClose>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </div>
        </div>
    )
}

function AddEmailForm(): JSX.Element {
    const { newEmailFromEmail, newEmailFromName, emailConnecting, addEmailFormVisible } =
        useValues(supportSettingsLogic)
    const { setNewEmailFromEmail, setNewEmailFromName, connectEmail, setAddEmailFormVisible } =
        useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const connectDisabledReason =
        adminRestrictionReason ??
        (!newEmailFromEmail || !newEmailFromName ? 'Enter email address and display name' : undefined)

    if (!addEmailFormVisible) {
        return (
            <div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAddEmailFormVisible(true)}
                    disabled={!!adminRestrictionReason}
                    title={adminRestrictionReason ?? undefined}
                >
                    <IconPlus />
                    Add email address
                </Button>
            </div>
        )
    }

    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-2">
                <label className="font-medium">Connect new email</label>
                <p className="text-xs text-muted-alt">
                    Enter the email address customers will contact you at (e.g. support@company.com). We'll give you a
                    forwarding address to set up in your email provider and register your domain for outbound sending.
                </p>
                <Input
                    className="w-full"
                    value={newEmailFromEmail}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setNewEmailFromEmail(e.target.value)}
                    placeholder="support@company.com"
                />
                <Input
                    className="w-full"
                    value={newEmailFromName}
                    onChange={(e: ChangeEvent<HTMLInputElement>) => setNewEmailFromName(e.target.value)}
                    placeholder="Display name (e.g. Acme Support)"
                />
                <div className="flex gap-2">
                    <Button
                        variant="primary"
                        size="sm"
                        onClick={connectEmail}
                        loading={emailConnecting}
                        disabled={!!connectDisabledReason}
                        title={connectDisabledReason}
                    >
                        Connect email
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setAddEmailFormVisible(false)}>
                        Cancel
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}

function configHeader(config: EmailConfigStatus): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 text-left">
            <span className="font-medium truncate">{config.from_email}</span>
            {config.from_name && <span className="text-xs text-muted truncate">({config.from_name})</span>}
            {config.is_default && (
                <Badge variant="info" className="shrink-0">
                    Primary
                </Badge>
            )}
            {config.domain_verified ? (
                <Badge variant="success" className="shrink-0">
                    Verified
                </Badge>
            ) : (
                <Badge variant="warning" className="shrink-0">
                    Unverified
                </Badge>
            )}
        </div>
    )
}

export function EmailSection(): JSX.Element {
    const { emailConfigs } = useValues(supportSettingsLogic)
    const [expandedKeys, setExpandedKeys] = useState<string[]>([])

    return (
        <SceneSection
            title="Email channel"
            description="Receive customer emails as support tickets and reply directly from PostHog. Set up forwarding and verify your domain to enable two-way email."
        >
            <div className="flex flex-col gap-3 max-w-[800px]">
                {emailConfigs.length > 0 && (
                    <Accordion
                        multiple
                        className="bg-surface-primary"
                        value={expandedKeys}
                        onValueChange={(keys) => setExpandedKeys(keys as string[])}
                    >
                        {emailConfigs.map((config: EmailConfigStatus) => (
                            <AccordionItem key={config.id} value={config.id}>
                                <AccordionTrigger>{configHeader(config)}</AccordionTrigger>
                                <AccordionContent>
                                    <EmailConfigContent config={config} />
                                </AccordionContent>
                            </AccordionItem>
                        ))}
                    </Accordion>
                )}
                <AddEmailForm />
            </div>
        </SceneSection>
    )
}
