import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBolt } from '@posthog/icons'
import { LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { SignalReportPriority } from '../../types'

const NEVER_AUTOSTART_VALUE = '__never__'

const USER_AUTOSTART_OPTIONS: { value: string; label: string }[] = [
    { value: NEVER_AUTOSTART_VALUE, label: 'Never – review everything first' },
    { value: 'P0', label: 'P0 – Critical only' },
    { value: 'P1', label: 'P1 – High and above' },
    { value: 'P2', label: 'P2 – Medium and above' },
    { value: 'P3', label: 'P3 – Low and above' },
    { value: 'P4', label: 'P4 – All priorities' },
]

export function AutoStartThresholdSection(): JSX.Element {
    useMountedLogic(userAutonomyLogic)
    const { autonomyConfig, autonomyConfigLoading } = useValues(userAutonomyLogic)
    const { loadAutonomyConfig, setAutostartPriority } = useActions(userAutonomyLogic)

    useEffect(() => {
        loadAutonomyConfig()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    const value = autonomyConfig?.autostart_priority ?? NEVER_AUTOSTART_VALUE

    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconBolt className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Your PR auto-start threshold</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Reports at or above this priority can start an implementation task for you. The backend
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
