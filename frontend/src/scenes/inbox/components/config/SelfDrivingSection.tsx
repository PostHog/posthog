import { useActions, useValues } from 'kea'

import { IconRocket } from '@posthog/icons'
import { LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { SignalReportPriority } from '../../types'

/** Minimum report priority that auto-starts an implementation PR. P4 admits every report. */
export const AUTOSTART_PRIORITY_OPTIONS: { value: SignalReportPriority; label: string }[] = [
    { value: 'P0', label: 'P0 only' },
    { value: 'P1', label: 'P1 and above' },
    { value: 'P2', label: 'P2 and above' },
    { value: 'P3', label: 'P3 and above' },
    { value: 'P4', label: 'P4 and above (all reports)' },
]

/**
 * Team-wide self-driving controls, backed by `autostart_enabled` and
 * `default_autostart_priority` on `signalTeamConfigLogic`. The switch is the master
 * opt-out for autonomous inbox PRs: only an explicit false disables auto-start, so a
 * team that never touched it stays on. Reports keep generating and notifying either
 * way. The threshold is the team default; a teammate's personal threshold (set via
 * their own autonomy config) takes precedence for reports suggesting them as reviewer.
 */
export function SelfDrivingSection(): JSX.Element {
    const { teamConfig, teamConfigLoading } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    const autostartEnabled = teamConfig?.autostart_enabled !== false
    const priority = teamConfig?.default_autostart_priority ?? 'P4'

    return (
        <div className="flex flex-col gap-3 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                    <IconRocket className="size-5 shrink-0 mt-0.5" />
                    <div className="min-w-0">
                        <div className="font-medium text-sm text-default">Start work automatically</div>
                        <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                            When a report is actionable and meets the threshold, an agent starts implementation and
                            opens a PR. When off, reports still arrive and notify — your team reviews and opens PRs
                            manually.
                        </p>
                    </div>
                </div>
                <LemonSwitch
                    checked={autostartEnabled}
                    onChange={(enabled) => patchTeamConfig({ autostart_enabled: enabled })}
                    aria-label="Start work on reports automatically"
                />
            </div>

            {autostartEnabled && (
                <div className="flex flex-col gap-1 min-w-0 border-t border-primary border-dashed pt-3">
                    <span className="text-xs text-secondary">Auto-start threshold</span>
                    <LemonSelect
                        className="max-w-[240px]"
                        value={priority}
                        options={AUTOSTART_PRIORITY_OPTIONS}
                        onChange={(next) => patchTeamConfig({ default_autostart_priority: next })}
                    />
                    <p className="text-xs text-tertiary mt-1 mb-0">
                        Team default — a teammate's personal threshold, if set, takes precedence for them.
                    </p>
                </div>
            )}
        </div>
    )
}
