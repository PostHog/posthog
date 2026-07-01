import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

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
    const { subdomain, emailAddress, apiToken, importJob, importJobLoading, isImportRunning, importProgressLabel } =
        useValues(zendeskImportLogic)
    const { setSubdomain, setEmailAddress, setApiToken, submitImport } = useActions(zendeskImportLogic)
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
                <p className="text-xs text-muted-alt m-0">
                    Imported {importJob.imported_tickets.toLocaleString()} tickets (
                    {importJob.skipped_tickets.toLocaleString()} skipped, {importJob.failed_tickets.toLocaleString()}{' '}
                    failed).
                </p>
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
                placeholder="Zendesk agent email"
                value={emailAddress}
                onChange={setEmailAddress}
                disabled={isImportRunning}
            />
            <LemonInput
                type="password"
                placeholder="Zendesk API token"
                value={apiToken}
                onChange={setApiToken}
                disabled={isImportRunning}
            />
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
