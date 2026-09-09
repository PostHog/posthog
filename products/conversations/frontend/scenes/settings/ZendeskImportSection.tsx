import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { zendeskImportLogic, ZendeskImportJobStatus } from './zendeskImportLogic'

const NO_DEFAULT_INBOX = '__none__'

function statusTag(status: ZendeskImportJobStatus | undefined): JSX.Element | null {
    if (!status) {
        return null
    }
    if (status === 'running' || status === 'pending') {
        return <Badge variant="warning">Syncing</Badge>
    }
    if (status === 'completed') {
        return <Badge variant="success">Done</Badge>
    }
    return <Badge variant="destructive">Failed</Badge>
}

export function ZendeskImportSection(): JSX.Element {
    return (
        <SceneSection
            title="Zendesk import"
            description="Import historical Zendesk Support tickets and message threads into Support. Already-synced tickets are skipped on re-run."
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent>
                    <ZendeskImportForm />
                </CardContent>
            </Card>
        </SceneSection>
    )
}

function ZendeskImportForm(): JSX.Element {
    const {
        subdomain,
        emailAddress,
        apiToken,
        defaultEmailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(zendeskImportLogic)
    const { setSubdomain, setEmailAddress, setApiToken, setDefaultEmailChannelId, submitImport } =
        useActions(zendeskImportLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const canSubmit = !!subdomain.trim() && !!emailAddress.trim() && !!apiToken.trim()
    const submitDisabledReason =
        adminRestrictionReason ||
        (isImportRunning ? 'Import already running' : !canSubmit ? 'Fill in all fields' : undefined)

    return (
        <div className="flex flex-col gap-y-3">
            <div className="flex items-center gap-2">
                <span className="font-medium">Import status</span>
                {statusTag(importJob?.status)}
                {importProgressLabel ? <span className="text-xs text-muted-alt">{importProgressLabel}</span> : null}
            </div>

            {importJob?.status === 'completed' ? (
                <>
                    <p className="text-xs text-muted-alt m-0">
                        Imported {importJob.imported_tickets.toLocaleString()} tickets (
                        {importJob.skipped_tickets.toLocaleString()} skipped,{' '}
                        {importJob.failed_tickets.toLocaleString()} failed).
                    </p>
                    <p className="text-xs text-muted-alt m-0">
                        If the imported total is lower than the latest ticket number in Zendesk, that is usually
                        expected. Ticket numbers count every ticket ever created, including gaps from deleted tickets.
                        The export API only returns tickets Zendesk still exposes: permanently deleted tickets (after
                        retention), archived tickets, and AI agent tickets may be omitted.
                    </p>
                </>
            ) : null}

            {importJob?.status === 'failed' && importJob.latest_error ? (
                <p className="text-xs text-danger m-0">{importJob.latest_error}</p>
            ) : null}

            <Input
                type="text"
                className="w-full"
                placeholder="Zendesk subdomain"
                value={subdomain}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setSubdomain(e.target.value)}
                disabled={isImportRunning}
            />
            <Input
                type="email"
                className="w-full"
                placeholder={
                    importJob?.has_credentials
                        ? 'Zendesk agent email (configured — re-enter to start a new import)'
                        : 'Zendesk agent email'
                }
                value={emailAddress}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setEmailAddress(e.target.value)}
                disabled={isImportRunning}
            />
            <Input
                type="password"
                className="w-full"
                placeholder={
                    importJob?.has_credentials
                        ? 'Zendesk API token (configured — re-enter to start a new import)'
                        : 'Zendesk API token'
                }
                value={apiToken}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setApiToken(e.target.value)}
                disabled={isImportRunning}
            />
            <Field>
                <FieldLabel>Default inbox</FieldLabel>
                <FieldDescription>
                    Fallback email channel for tickets whose original Zendesk recipient doesn't match one of your
                    configured support addresses (e.g. a *.zendesk.com address, or a non-email ticket). Tickets that do
                    match are assigned to the matching channel regardless of this setting.
                </FieldDescription>
                <Select
                    value={defaultEmailChannelId ?? NO_DEFAULT_INBOX}
                    onValueChange={(value) => setDefaultEmailChannelId(value === NO_DEFAULT_INBOX ? null : value)}
                    disabled={isImportRunning}
                >
                    <SelectTrigger>
                        <SelectValue placeholder="No default (leave unmatched tickets without an inbox)" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value={NO_DEFAULT_INBOX}>No default</SelectItem>
                        {emailConfigs.map((config) => (
                            <SelectItem key={config.id} value={config.id}>
                                {config.from_email}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </Field>
            {defaultEmailChannelId === null && !isImportRunning && (
                <div className="rounded border border-warning bg-warning-highlight p-2 text-sm">
                    Without a default inbox, tickets whose Zendesk address doesn't match one of your connected support
                    addresses are imported without an email channel. Agents won't be able to reply to those customers by
                    email, and the reply box on those tickets will be disabled.
                </div>
            )}
            <div>
                <Button
                    variant="primary"
                    onClick={submitImport}
                    loading={importJobLoading}
                    disabled={!!submitDisabledReason}
                    title={submitDisabledReason ?? undefined}
                >
                    Start import
                </Button>
            </div>
        </div>
    )
}
