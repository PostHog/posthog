import { useActions, useValues } from 'kea'

import { IconRocket } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

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
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-xs text-secondary shrink-0">Threshold</span>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={defaultAutostartPriority}
                            options={THRESHOLD_SEGMENTS}
                            onChange={(next) => patchTeamConfig({ default_autostart_priority: next })}
                        />
                    </div>
                ) : (
                    <p className="text-xs text-secondary mb-0">Reports still arrive and notify your team.</p>
                )}
            </div>
        </div>
    )
}
