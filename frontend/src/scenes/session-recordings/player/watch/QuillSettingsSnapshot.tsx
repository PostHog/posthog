import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Skeleton } from '@posthog/quill'

import { settingsSnapshotLogic } from 'lib/components/settingsSnapshotLogic'

function settingLabel(key: string): string {
    return key
        .replaceAll('_', ' ')
        .replace('session recording', 'Session recording')
        .replace('session replay', 'Session replay')
}

function settingDisplay(value: unknown): string {
    if (value === null || value === undefined || value === '') {
        return 'Not set'
    }
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** Quill sibling of `SettingsSnapshot`: the project's replay settings as they were when the recording was captured. */
export function QuillSettingsSnapshot({ at, scope }: { at?: string; scope: string[] }): JSX.Element {
    const { loadSettingsAsOf } = useActions(settingsSnapshotLogic)
    const { settingsSnapshot, settingsSnapshotLoading } = useValues(settingsSnapshotLogic)
    const scopeKey = scope.join('|')

    useEffect(() => {
        if (at) {
            loadSettingsAsOf(at, scope)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [at, scopeKey])

    if (!at) {
        return <div className="px-2 py-1 text-sm text-muted-foreground">No timestamp provided.</div>
    }
    if (settingsSnapshotLoading) {
        return (
            <div className="flex flex-col gap-2 p-2">
                <Skeleton className="h-4" />
                <Skeleton className="h-4" />
            </div>
        )
    }
    const snapshot = (settingsSnapshot ?? {}) as Record<string, unknown>
    const keys = scope.filter((key) => key in snapshot)
    if (keys.length === 0) {
        return <div className="px-2 py-1 text-sm text-muted-foreground">No settings to display.</div>
    }
    return (
        <div
            className="flex flex-col divide-y divide-border rounded border border-border"
            data-attr="watch-overview-settings"
        >
            {keys.map((key) => (
                <div key={key} className="flex items-start justify-between gap-4 px-2 py-1 text-sm">
                    <span className="shrink-0 max-w-[50%] font-light">{settingLabel(key)}</span>
                    <code className="min-w-0 break-all text-right text-xs">{settingDisplay(snapshot[key])}</code>
                </div>
            ))}
        </div>
    )
}
