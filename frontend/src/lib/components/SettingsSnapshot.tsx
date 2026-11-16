import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { settingsSnapshotLogic } from './settingsSnapshotLogic'

type Props = {
    at?: string
    scope: string[]
    title?: string
    showHeader?: boolean
    className?: string
    layout?: 'list' | 'grid'
}

export function SettingsSnapshot({
    at,
    scope,
    title = 'Settings at the time of the event',
    showHeader = true,
    className,
    layout = 'list',
}: Props): JSX.Element | null {
    const { loadSettingsAsOf } = useActions(settingsSnapshotLogic)
    const { settingsSnapshot, settingsSnapshotLoading } = useValues(settingsSnapshotLogic)

    const scopeKey = useMemo(() => scope.join('|'), [scope])

    useEffect(() => {
        // Backend requires `at` - only fetch when provided
        if (at) {
            loadSettingsAsOf(at, scope)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [at, scopeKey])

    const header = showHeader ? <div className="font-semibold text-muted mb-1">{title}</div> : null

    // If no timestamp is provided, we don't fetch – show empty state/header if requested
    if (!at) {
        return showHeader ? (
            <div className={className}>
                {header}
                <div className="text-muted text-xs">No timestamp provided.</div>
            </div>
        ) : null
    }

    if (settingsSnapshotLoading) {
        return (
            <div className={className}>
                {header}
                <div className="flex flex-col deprecated-space-y-1 w-full">
                    <LemonSkeleton.Row repeat={2} className="h-4" />
                </div>
            </div>
        )
    }

    if (!settingsSnapshot) {
        return showHeader ? (
            <div className={className}>
                {header}
                <div className="text-muted text-xs">No settings to display.</div>
            </div>
        ) : null
    }

    const keysToRender = scope.filter((k) => k in (settingsSnapshot as Record<string, any>))

    return (
        <div className={className}>
            {header}
            {keysToRender.length === 0 ? (
                showHeader ? (
                    <div className="text-muted text-xs">No settings to display.</div>
                ) : null
            ) : (
                <div
                    className={
                        layout === 'grid' ? 'grid grid-cols-3 gap-2 items-start [&>*]:min-w-0' : 'flex flex-col gap-2'
                    }
                >
                    {keysToRender.map((key) => {
                        const label = key
                            .replaceAll('_', ' ')
                            .replace('session recording', 'Session recording')
                            .replace('session replay', 'Session replay')
                        const value = (settingsSnapshot as any)[key]
                        const display =
                            value !== null && typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
                        return (
                            <div key={key} className="rounded border p-2">
                                <div className="text-muted text-xs mb-1">{label}</div>
                                <pre className="text-xs whitespace-pre-wrap break-words m-0">{display}</pre>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
