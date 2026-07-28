import { useActions, useValues } from 'kea'

import { IconPlus, IconRocket, IconX } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { GitHubBranchCombobox } from 'lib/integrations/GitHubBranchCombobox'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { PRIORITY_THRESHOLD_OPTIONS, SignalReportPriority } from '../../types'

/** Compact segmented-control label per priority. P4 (the lowest bar) reads as "All". */
const THRESHOLD_SEGMENT_LABELS: Record<SignalReportPriority, string> = {
    P0: 'P0',
    P1: 'P1+',
    P2: 'P2+',
    P3: 'P3+',
    P4: 'All',
}
/** Segments derived from the shared priority list, so the value set and order stay single-sourced. */
const THRESHOLD_SEGMENTS = PRIORITY_THRESHOLD_OPTIONS.map(({ value }) => ({
    value,
    label: THRESHOLD_SEGMENT_LABELS[value],
}))

function BaseBranchOverrideRows(): JSX.Element | null {
    const { baseBranchOverrides } = useValues(signalTeamConfigLogic)
    const { updateBaseBranchOverride, removeBaseBranchOverride } = useActions(signalTeamConfigLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    if (baseBranchOverrides.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1">
            {baseBranchOverrides.map(({ repo, branch }) => {
                const integration = githubIntegrations.find(
                    (candidate) => candidate.display_name.toLowerCase() === repo.split('/')[0]
                )
                return (
                    <div key={repo} className="flex items-center gap-1">
                        <span className="text-xs text-default min-w-0 flex-1 truncate" title={repo}>
                            {repo}
                        </span>
                        {integration ? (
                            <GitHubBranchCombobox
                                integrationId={integration.id}
                                repo={repo}
                                value={branch}
                                onChange={(next) => {
                                    if (next) {
                                        updateBaseBranchOverride(repo, next)
                                    }
                                }}
                            />
                        ) : (
                            <span className="text-xs text-muted shrink-0">{branch}</span>
                        )}
                        <Button
                            variant="outline"
                            size="sm"
                            aria-label={`Remove base branch override for ${repo}`}
                            onClick={() => removeBaseBranchOverride(repo)}
                        >
                            <IconX />
                        </Button>
                    </div>
                )
            })}
        </div>
    )
}

function BaseBranchOverridePicker({ integrationIds }: { integrationIds: number[] }): JSX.Element {
    const { draftBaseBranchIntegrationId, draftBaseBranchRepo, draftBaseBranchBranch, canAddBaseBranchOverride } =
        useValues(signalTeamConfigLogic)
    const { setDraftBaseBranchIntegrationId, setDraftBaseBranchRepo, setDraftBaseBranchBranch, addBaseBranchOverride } =
        useActions(signalTeamConfigLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    const integrationId = draftBaseBranchIntegrationId ?? integrationIds[0]
    const githubIntegrations = getIntegrationsByKind(['github'])

    return (
        <div className="flex flex-wrap items-center gap-1">
            {integrationIds.length > 1 && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button variant="outline" size="sm" aria-label="GitHub organization">
                                <span className="min-w-0 truncate">
                                    {githubIntegrations.find((integration) => integration.id === integrationId)
                                        ?.display_name ?? 'GitHub'}
                                </span>
                            </Button>
                        }
                    />
                    <DropdownMenuContent>
                        {githubIntegrations.map((integration) => (
                            <DropdownMenuItem
                                key={integration.id}
                                onClick={() => setDraftBaseBranchIntegrationId(integration.id)}
                            >
                                {integration.display_name}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            <ButtonGroup>
                <GitHubRepositoryCombobox
                    integrationId={integrationId}
                    value={draftBaseBranchRepo}
                    onChange={(repo) => setDraftBaseBranchRepo(repo ?? '')}
                    placeholder="Repository"
                />
                {draftBaseBranchRepo ? (
                    <GitHubBranchCombobox
                        integrationId={integrationId}
                        repo={draftBaseBranchRepo}
                        value={draftBaseBranchBranch}
                        onChange={(branch) => setDraftBaseBranchBranch(branch ?? '')}
                    />
                ) : null}
            </ButtonGroup>
            <Button
                variant="outline"
                size="sm"
                disabled={!canAddBaseBranchOverride}
                aria-label="Add base branch override"
                onClick={() => addBaseBranchOverride()}
            >
                <IconPlus />
            </Button>
        </div>
    )
}

function BaseBranchOverrides(): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const integrationIds = getIntegrationsByKind(['github']).map((integration) => integration.id)

    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-xs text-secondary">Base branches</span>
            <p className="text-[11px] text-tertiary leading-snug mb-0">
                PRs open against each repository's default branch. Add an override to target a different branch, like
                develop.
            </p>
            <BaseBranchOverrideRows />
            {integrationIds.length > 0 ? (
                <BaseBranchOverridePicker integrationIds={integrationIds} />
            ) : (
                <p className="text-[11px] text-tertiary leading-snug mb-0">
                    Connect GitHub above to choose a base branch.
                </p>
            )}
        </div>
    )
}

/**
 * Team-wide PR-generation control, backed by `autostart_enabled` and `default_autostart_priority`
 * on `signalTeamConfigLogic`. The inline switch is the master opt-out for autonomous inbox PRs;
 * reports keep generating and notifying either way. The threshold is the team default; a teammate's
 * personal threshold takes precedence for reports suggesting them as reviewer.
 *
 * A standalone card rather than a `SetupWidgetCard` because it hosts inline controls (the switch and
 * threshold) that can't live inside that card's single button/link wrapper.
 */
export function SelfDrivingSection(): JSX.Element {
    const { teamConfig, teamConfigLoading, autostartEnabled, defaultAutostartPriority } =
        useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-20 w-full rounded" />
    }

    return (
        <div className="flex flex-col rounded border border-primary bg-surface-primary overflow-hidden">
            <div className="flex items-start gap-2 px-2.5 py-2">
                <span className="flex size-7 shrink-0 items-center justify-center rounded bg-surface-secondary text-default [&_svg]:size-4">
                    <IconRocket />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-semibold text-default">PR generation</span>
                        <LemonSwitch
                            checked={autostartEnabled}
                            onChange={(enabled) => patchTeamConfig({ autostart_enabled: enabled })}
                            aria-label="Generate PRs for actionable reports automatically"
                        />
                    </div>
                    <p className="text-xs text-tertiary leading-snug mb-0">Agents open PRs for actionable reports.</p>
                </div>
            </div>

            <div className="border-t border-primary bg-surface-secondary px-2.5 py-1.5">
                {autostartEnabled ? (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs text-secondary shrink-0">Threshold</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={defaultAutostartPriority}
                                options={THRESHOLD_SEGMENTS}
                                onChange={(next) => patchTeamConfig({ default_autostart_priority: next })}
                            />
                        </div>
                        <BaseBranchOverrides />
                    </div>
                ) : (
                    <p className="text-xs text-secondary mb-0">Reports still arrive and notify your team.</p>
                )}
            </div>
        </div>
    )
}
