import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { zendeskImportLogic, ZendeskImportJobStatus } from './zendeskImportLogic'

function statusTag(status: ZendeskImportJobStatus | undefined): JSX.Element | null {
    if (!status) {
        return null
    }
    if (status === 'running' || status === 'pending') {
        return (
            <LemonTag type="warning" size="small">
                Syncing
            </LemonTag>
        )
    }
    if (status === 'completed') {
        return (
            <LemonTag type="success" size="small">
                Done
            </LemonTag>
        )
    }
    return (
        <LemonTag type="danger" size="small">
            Failed
        </LemonTag>
    )
}

export function ZendeskImportSection(): JSX.Element {
    return (
        <SceneSection
            title="Zendesk import"
            description="Import historical Zendesk Support tickets and message threads into Conversations. Already-synced tickets are skipped on re-run."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <ZendeskImportForm />
            </LemonCard>
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

            <LemonInput
                type="text"
                placeholder="Zendesk subdomain"
                value={subdomain}
                onChange={setSubdomain}
                disabled={isImportRunning}
            />
            <LemonInput
                type="email"
                placeholder={
                    importJob?.has_credentials
                        ? 'Zendesk agent email (configured — re-enter to start a new import)'
                        : 'Zendesk agent email'
                }
                value={emailAddress}
                onChange={setEmailAddress}
                disabled={isImportRunning}
            />
            <LemonInput
                type="password"
                placeholder={
                    importJob?.has_credentials
                        ? 'Zendesk API token (configured — re-enter to start a new import)'
                        : 'Zendesk API token'
                }
                value={apiToken}
                onChange={setApiToken}
                disabled={isImportRunning}
            />
            <LemonField.Pure
                label="Default inbox"
                info="Fallback email channel for tickets whose original Zendesk recipient doesn't match one of your configured support addresses (e.g. a *.zendesk.com address, or a non-email ticket). Tickets that do match are assigned to the matching channel regardless of this setting."
            >
                <LemonSelect<string | null>
                    value={defaultEmailChannelId}
                    onChange={setDefaultEmailChannelId}
                    disabled={isImportRunning}
                    placeholder="No default (leave unmatched tickets without an inbox)"
                    options={[
                        { label: 'No default', value: null },
                        ...emailConfigs.map((config) => ({ label: config.from_email, value: config.id })),
                    ]}
                />
            </LemonField.Pure>
            <div>
                <LemonButton
                    type="primary"
                    onClick={submitImport}
                    loading={importJobLoading}
                    disabledReason={
                        adminRestrictionReason ||
                        (isImportRunning ? 'Import already running' : !canSubmit ? 'Fill in all fields' : undefined)
                    }
                >
                    Start import
                </LemonButton>
            </div>
        </div>
    )
}
