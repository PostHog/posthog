import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBolt, IconPeople } from '@posthog/icons'
import { LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { SignalReportPriority } from '../../types'

const NEVER_AUTOSTART_VALUE = '__never__'

/** P0–P4, matching desktop `AUTOSTART_PRIORITY_OPTIONS`. The team default is non-nullable, so no "Never". */
const TEAM_AUTOSTART_OPTIONS: { value: SignalReportPriority; label: string }[] = [
    { value: 'P0', label: 'P0 – Critical only' },
    { value: 'P1', label: 'P1 – High and above' },
    { value: 'P2', label: 'P2 – Medium and above' },
    { value: 'P3', label: 'P3 – Low and above' },
    { value: 'P4', label: 'P4 – All priorities' },
]

/** Per-user override adds "Never – review everything first" on top of the team options. */
const USER_AUTOSTART_OPTIONS: { value: string; label: string }[] = [
    { value: NEVER_AUTOSTART_VALUE, label: 'Never – review everything first' },
    ...TEAM_AUTOSTART_OPTIONS,
]

function TeamDefaultRow(): JSX.Element {
    useMountedLogic(signalTeamConfigLogic)
    const { teamConfig, teamConfigLoading } = useValues(signalTeamConfigLogic)
    const { loadTeamConfig, setDefaultAutostartPriority } = useActions(signalTeamConfigLogic)

    useEffect(() => {
        loadTeamConfig()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    // Backend defaults this to P2, but the row may be unloaded; fall back to P2 for display.
    const value = teamConfig?.default_autostart_priority ?? 'P2'

    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconPeople className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Team default auto-create PR threshold</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        The starting point for everyone on this team. Individuals can override it for themselves below.
                    </p>
                </div>
            </div>
            {teamConfigLoading && teamConfig === null ? (
                <LemonSkeleton className="h-8 w-[260px] shrink-0" />
            ) : (
                <LemonSelect
                    className="min-w-[260px] shrink-0"
                    value={value}
                    options={TEAM_AUTOSTART_OPTIONS}
                    onChange={(next) => setDefaultAutostartPriority(next as SignalReportPriority)}
                />
            )}
        </div>
    )
}

function UserOverrideRow(): JSX.Element {
    useMountedLogic(userAutonomyLogic)
    const { autonomyConfig, autonomyConfigLoading } = useValues(userAutonomyLogic)
    const { setAutostartPriority } = useActions(userAutonomyLogic)

    const value = autonomyConfig?.autostart_priority ?? NEVER_AUTOSTART_VALUE

    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconBolt className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Your auto-create PR threshold</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Reports at or above this priority automatically open a pull request for you. The backend
                        deduplicates per report, and these runs count toward usage.
                    </p>
                </div>
            </div>
            {autonomyConfigLoading && autonomyConfig === null ? (
                <LemonSkeleton className="h-8 w-[260px] shrink-0" />
            ) : (
                <LemonSelect
                    className="min-w-[260px] shrink-0"
                    value={value}
                    options={USER_AUTOSTART_OPTIONS}
                    onChange={(next) =>
                        setAutostartPriority(next === NEVER_AUTOSTART_VALUE ? null : (next as SignalReportPriority))
                    }
                />
            )}
        </div>
    )
}

export function AutoStartThresholdSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <TeamDefaultRow />
            <UserOverrideRow />
        </div>
    )
}
