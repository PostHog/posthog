import { useActions, useValues } from 'kea'

import { IconPlus, IconRocket } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonSnack,
    LemonSwitch,
} from '@posthog/lemon-ui'

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

/**
 * Per-repo base-branch overrides for auto-started PRs. Auto-PRs target the repo default branch
 * unless a repo is mapped here (e.g. teams on a develop-then-master or QA-then-main flow). Backed by
 * `autostart_base_branches` on `signalTeamConfigLogic`; the whole map is persisted on each change.
 */
function BaseBranchOverrides(): JSX.Element {
    const { baseBranchOverrides, draftBaseBranchRepo, draftBaseBranchBranch } = useValues(signalTeamConfigLogic)
    const { setDraftBaseBranchRepo, setDraftBaseBranchBranch, addBaseBranchOverride, removeBaseBranchOverride } =
        useActions(signalTeamConfigLogic)

    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-xs text-secondary">Base branches</span>
            <p className="text-[11px] text-tertiary leading-snug mb-0">
                Auto-PRs target each repo's default branch. Override it per repo to open PRs against another branch,
                like develop or QA.
            </p>
            {baseBranchOverrides.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {baseBranchOverrides.map(({ repo, branch }) => (
                        <LemonSnack
                            key={repo}
                            title={`${repo} → ${branch}`}
                            onClose={() => removeBaseBranchOverride(repo)}
                        >
                            <span className="text-default">{repo}</span>
                            <span className="text-muted"> → {branch}</span>
                        </LemonSnack>
                    ))}
                </div>
            )}
            <div className="flex items-center gap-1">
                <LemonInput
                    size="xsmall"
                    className="flex-1 min-w-0"
                    placeholder="organization/repository"
                    value={draftBaseBranchRepo}
                    onChange={setDraftBaseBranchRepo}
                    onPressEnter={addBaseBranchOverride}
                />
                <LemonInput
                    size="xsmall"
                    className="flex-1 min-w-0"
                    placeholder="branch"
                    value={draftBaseBranchBranch}
                    onChange={setDraftBaseBranchBranch}
                    onPressEnter={addBaseBranchOverride}
                />
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={addBaseBranchOverride}
                    disabledReason={
                        !draftBaseBranchRepo.trim() || !draftBaseBranchBranch.trim()
                            ? 'Enter a repository and a branch'
                            : undefined
                    }
                    aria-label="Add base branch override"
                />
            </div>
        </div>
    )
}

/**
 * Team-wide PR-generation control, backed by `autostart_enabled` and `default_autostart_priority`
 * on `signalTeamConfigLogic`. The inline switch is the master opt-out for autonomous inbox PRs;
 * reports keep generating and notifying either way. The threshold is the team default; a teammate's
 * personal threshold takes precedence for reports suggesting them as reviewer. When enabled, the card
 * also exposes per-repo base-branch overrides for the opened PRs.
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
