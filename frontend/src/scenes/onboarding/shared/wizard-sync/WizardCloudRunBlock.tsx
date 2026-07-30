import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCheckCircle, IconChevronDown, IconGithub, IconPullRequest, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    GitHubRepositoryPicker,
    type RepositoryPickerSummary,
    githubManageInstallationUrl,
} from 'lib/integrations/GitHubIntegrationHelpers'
import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'

import { IntegrationType } from '~/types'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import { InstallationProgressView } from './InstallationProgressView'
import { wizardCloudRunLogic } from './wizardCloudRunLogic'
import { WizardModeShell } from './WizardModeShell'

/**
 * The primary, "we'll do it for you" way to run the wizard: connect GitHub, pick a
 * repo, and we run the same instrumentation wizard on our infra and open a pull
 * request you review and merge. Shares WizardModeShell (hog + framework badges)
 * with the local command tab so both read as one wizard.
 *
 * Deliberately non-blocking: kicking off a run flips to live progress — the
 * Installation layer (installationProgressLogic / InstallationProgressView)
 * streams the run's pipeline — and the user can hit Continue right away.
 */
export function WizardCloudRunBlock({
    onQueued,
    hideHog = false,
    onRetryLocally,
}: {
    onQueued?: () => void
    hideHog?: boolean
    /** Forwarded to the install progress view so a failed run can offer "Run it yourself". */
    onRetryLocally?: () => void
}): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const syncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { githubIntegration, selectedRepository, cloudRunStatus, connectGitHubUrl } = useValues(wizardCloudRunLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { setSelectedRepository, startCloudRun } = useActions(wizardCloudRunLogic)
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)

    // Fire onQueued once per kickoff, the moment the run is handed off. It advances the install step
    // (GROW-96), so it must not repeat while the status stays 'queued' (the callback identity changes
    // each render). Reset when the run leaves 'queued' so a later run can advance the flow again.
    const queuedAdvancedRef = useRef(false)
    useEffect(() => {
        if (cloudRunStatus === 'queued') {
            if (!queuedAdvancedRef.current) {
                queuedAdvancedRef.current = true
                onQueued?.()
            }
        } else {
            queuedAdvancedRef.current = false
        }
    }, [cloudRunStatus, onQueued])

    // The cloud wizard only targets cloud (US/EU) and dev instances; nothing to
    // offer on self-hosted.
    if (!isCloudOrDev) {
        return <></>
    }

    // A spawned run (persisted handle) shows live progress and survives revisits, where the local
    // cloudRunStatus resets. While a run is active the parent blocks the local command (GROW-95), so
    // this is the only thing the cloud tab shows.
    if (activeCloudRun) {
        return (
            <InstallationProgressView
                mode="cloud"
                runId={activeCloudRun.runId}
                taskId={activeCloudRun.taskId}
                onRetryLocally={onRetryLocally}
                onDismiss={clearActiveCloudRun}
            />
        )
    }

    if (cloudRunStatus === 'queued') {
        const repoLabel = selectedRepository ? <span className="font-mono">{selectedRepository}</span> : 'your repo'
        // The brief window after kickoff before the run handle settles. With sync on the Installation
        // layer takes over above; without sync we cannot observe the run, so set honest expectations.
        return (
            <LemonBanner type="info">
                <div className="space-y-1" data-attr="wizard-cloud-run-queued">
                    {syncEnabled ? (
                        <>
                            <div className="font-semibold">Starting your cloud run…</div>
                            <div className="text-sm text-muted">
                                Kicking off the wizard on {repoLabel}. Progress will appear here in a moment and stays
                                in the corner as you keep going.
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="font-semibold">Cloud run queued for {repoLabel}.</div>
                            <div className="text-sm text-muted">
                                If it succeeds we'll open a pull request in your repo to review. We can't show live
                                progress here, so keep an eye on your repository.
                            </div>
                        </>
                    )}
                </div>
            </LemonBanner>
        )
    }

    return (
        <WizardModeShell hideHog={hideHog} data-attr="wizard-cloud-run-block">
            <p className="text-sm text-muted mb-0">
                We'll run the wizard against your repo and open a pull request with the SDK installed and events
                flowing. Review it and merge whenever you're ready.
            </p>

            {!githubIntegration ? (
                <LemonButton
                    type="secondary"
                    icon={<IconGithub />}
                    to={connectGitHubUrl}
                    disableClientSideRouting
                    data-attr="wizard-cloud-run-connect-github"
                    className={hideHog ? 'self-center' : 'self-start'}
                >
                    Connect GitHub
                </LemonButton>
            ) : (
                <RepositoryPicker
                    integration={githubIntegration}
                    selectedRepository={selectedRepository}
                    onSelectRepository={setSelectedRepository}
                    onStart={startCloudRun}
                    submitting={cloudRunStatus === 'submitting'}
                    connectGitHubUrl={connectGitHubUrl}
                />
            )}
        </WizardModeShell>
    )
}

/**
 * Repo picking, and every way out of it. The list comes from a GitHub App installation that may not
 * cover the repo the user wants, and is served from a cache that can be an hour stale — so the escape
 * hatches (widen the installation, re-sync the list) are always on screen, not just once it's empty.
 */
function RepositoryPicker({
    integration,
    selectedRepository,
    onSelectRepository,
    onStart,
    submitting,
    connectGitHubUrl,
}: {
    integration: IntegrationType
    selectedRepository: string | null
    onSelectRepository: (repository: string | null) => void
    onStart: () => void
    submitting: boolean
    /** Fallback when we don't know the installation id — re-runs the App authorize flow. */
    connectGitHubUrl: string
}): JSX.Element {
    const { repositoriesRefreshing } = useValues(githubIntegrationLogic({ id: integration.id }))
    const { refreshRepositories } = useActions(githubIntegrationLogic({ id: integration.id }))
    const { reportContextOnboardingRepositoryPickerDegraded } = useActions(onboardingEventUsageLogic)

    const [summary, setSummary] = useState<RepositoryPickerSummary | null>(null)

    const onRepositoriesLoaded = useCallback(
        (loaded: RepositoryPickerSummary) => {
            setSummary(loaded)
            if (loaded.total === 0 || loaded.pushable === 0) {
                reportContextOnboardingRepositoryPickerDegraded({
                    integrationId: integration.id,
                    reason: loaded.total === 0 ? 'empty' : 'all_unpushable',
                    totalCount: loaded.total,
                    pushableCount: loaded.pushable,
                })
            }
        },
        [integration.id, reportContextOnboardingRepositoryPickerDegraded]
    )

    const manageUrl = githubManageInstallationUrl(integration) ?? connectGitHubUrl
    const noneUsable = !!summary && summary.pushable === 0
    const escapeHatches = (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span>Repository not listed?</span>
            <Link to={manageUrl} target="_blank" data-attr="wizard-cloud-run-manage-github-access">
                Manage GitHub access
            </Link>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconRefresh />}
                onClick={() => refreshRepositories()}
                loading={repositoriesRefreshing}
                data-attr="wizard-cloud-run-refresh-repositories"
            >
                Refresh list
            </LemonButton>
        </div>
    )

    return (
        <div className="flex w-full flex-col gap-2">
            <div className="flex items-center gap-2">
                <div className="relative flex-1">
                    <IconGithub className="absolute left-2 top-1/2 -translate-y-1/2 z-10 text-base text-muted pointer-events-none" />
                    <GitHubRepositoryPicker
                        integrationId={integration.id}
                        value={selectedRepository ?? ''}
                        onChange={(repository) => onSelectRepository(repository)}
                        // We push a branch and open a PR, so read-only repos are shown but not pickable.
                        requireWriteAccess
                        onRepositoriesLoaded={onRepositoriesLoaded}
                        emptyStateComponent={
                            <div className="p-2 space-y-1 text-xs text-muted">
                                <div className="font-semibold text-default">No repositories available</div>
                                <div>This GitHub installation doesn't give PostHog access to any repository yet.</div>
                                {escapeHatches}
                            </div>
                        }
                        // Make the combobox read as a dropdown, not a text field: the LemonInput
                        // root defaults to `cursor: text` (unlayered SCSS), so override with `!`.
                        className="pl-7 pr-7 !cursor-pointer"
                    />
                    {!selectedRepository && (
                        <IconChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 z-10 text-base text-muted pointer-events-none" />
                    )}
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconPullRequest />}
                    onClick={() => onStart()}
                    loading={submitting}
                    disabledReason={
                        noneUsable
                            ? "We can't open a pull request in any of the repositories PostHog can see"
                            : selectedRepository
                              ? undefined
                              : 'Pick a repository first'
                    }
                    data-attr="wizard-cloud-run-open-pr"
                >
                    Install PostHog here
                </LemonButton>
            </div>
            {noneUsable && (
                <LemonBanner type="warning">
                    {/* LemonBanner doesn't forward data-attr to the DOM, so it goes on the inner div —
                        same as the queued banner above. */}
                    <div className="space-y-1 text-sm" data-attr="wizard-cloud-run-no-usable-repositories">
                        <div className="font-semibold">
                            {summary?.total === 0
                                ? 'PostHog has access to no repositories'
                                : "PostHog can't open a pull request in any repository it can see"}
                        </div>
                        <div className="text-muted">
                            {summary?.total === 0
                                ? 'Grant the PostHog GitHub App access to the repository you want to instrument, then refresh the list.'
                                : 'Every repository listed is read-only for the PostHog GitHub App. Grant it write access to the repository you want to instrument, or run the wizard yourself instead.'}
                        </div>
                    </div>
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <IconCheckCircle className="text-success" />
                    <span>Connected{integration.display_name ? ` to ${integration.display_name}` : ''}</span>
                </div>
                {escapeHatches}
            </div>
        </div>
    )
}
