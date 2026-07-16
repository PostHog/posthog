import { useActions, useValues } from 'kea'

import { IconRocket } from '@posthog/icons'
import { LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { PRIORITY_THRESHOLD_OPTIONS } from '../../types'
import { ConfigCardHeader } from './ConfigCardHeader'

/**
 * Team-wide self-driving controls, backed by `autostart_enabled` and
 * `default_autostart_priority` on `signalTeamConfigLogic`. The switch is the master
 * opt-out for autonomous inbox PRs; reports keep generating and notifying either
 * way. The threshold is the team default; a teammate's personal threshold (set via
 * their own autonomy config) takes precedence for reports suggesting them as reviewer.
 */
export function SelfDrivingSection(): JSX.Element {
    const { teamConfig, teamConfigLoading, autostartEnabled, defaultAutostartPriority } =
        useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    return (
        <div className="flex flex-col gap-3 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start justify-between gap-4">
                <ConfigCardHeader
                    icon={<IconRocket className="size-5 shrink-0 mt-0.5" />}
                    title="Start work automatically"
                    description="When a report is actionable and meets the threshold, an agent starts implementation and opens a PR. When off, reports still arrive and notify — your team reviews and opens PRs manually."
                />
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
                        value={defaultAutostartPriority}
                        options={PRIORITY_THRESHOLD_OPTIONS}
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
