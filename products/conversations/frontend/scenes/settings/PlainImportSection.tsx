import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { plainImportLogic, PlainImportJobStatus, PlainImportRegion } from './plainImportLogic'

function statusTag(status: PlainImportJobStatus | undefined): JSX.Element | null {
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

export function PlainImportSection(): JSX.Element {
    return (
        <SceneSection
            title="Plain import"
            description="Import historical Plain threads and message timelines into Conversations. Already-synced threads are skipped on re-run."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <PlainImportForm />
            </LemonCard>
        </SceneSection>
    )
}

function PlainImportForm(): JSX.Element {
    const {
        apiKey,
        region,
        defaultEmailChannelId,
        emailConfigs,
        importJob,
        importJobLoading,
        isImportRunning,
        importProgressLabel,
    } = useValues(plainImportLogic)
    const { setApiKey, setRegion, setDefaultEmailChannelId, submitImport } = useActions(plainImportLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const canSubmit = !!apiKey.trim() && !!region

    return (
        <div className="flex flex-col gap-y-3">
            <div className="flex items-center gap-2">
                <span className="font-medium">Import status</span>
                {statusTag(importJob?.status)}
                {importProgressLabel ? <span className="text-xs text-muted-alt">{importProgressLabel}</span> : null}
            </div>

            {importJob?.status === 'completed' ? (
                <p className="text-xs text-muted-alt m-0">
                    Imported {importJob.imported_tickets.toLocaleString()} threads (
                    {importJob.skipped_tickets.toLocaleString()} skipped, {importJob.failed_tickets.toLocaleString()}{' '}
                    failed).
                </p>
            ) : null}

            {importJob?.status === 'failed' && importJob.latest_error ? (
                <p className="text-xs text-danger m-0">{importJob.latest_error}</p>
            ) : null}

            <LemonField.Pure label="Region" info="Choose the Plain API region that matches your workspace.">
                <LemonSelect<PlainImportRegion>
                    value={region}
                    onChange={(value) => value && setRegion(value)}
                    disabled={isImportRunning}
                    options={[
                        { label: 'UK (core-api.uk.plain.com)', value: 'uk' },
                        { label: 'US (core-api.us.plain.com)', value: 'us' },
                    ]}
                />
            </LemonField.Pure>
            <LemonInput
                type="password"
                placeholder={
                    importJob?.has_credentials
                        ? 'Plain API key (configured — re-enter to start a new import)'
                        : 'Plain API key'
                }
                value={apiKey}
                onChange={setApiKey}
                disabled={isImportRunning}
            />
            <LemonField.Pure
                label="Default inbox"
                info="Fallback email channel for email-sourced Plain threads. Non-email threads (Slack, chat, etc.) are imported without an email channel."
            >
                <LemonSelect<string | null>
                    value={defaultEmailChannelId}
                    onChange={setDefaultEmailChannelId}
                    disabled={isImportRunning}
                    placeholder="No default (leave email threads without an inbox)"
                    options={[
                        { label: 'No default', value: null },
                        ...emailConfigs.map((config) => ({ label: config.from_email, value: config.id })),
                    ]}
                />
            </LemonField.Pure>
            {defaultEmailChannelId === null && !isImportRunning && (
                <LemonBanner type="warning">
                    Without a default inbox, email-sourced Plain threads are imported without an email channel. Agents
                    won't be able to reply to those customers by email, and the reply box on those tickets will be
                    disabled.
                </LemonBanner>
            )}
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
