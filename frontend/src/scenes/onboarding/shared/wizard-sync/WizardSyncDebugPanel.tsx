import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { pluralize } from 'lib/utils/strings'
import { type SyncDebugKind, wizardSyncDebugLogic } from 'lib/wizard-sync/wizardSyncDebugLogic'

const KIND_COLORS: Record<SyncDebugKind, string> = {
    connect: 'text-muted',
    open: 'text-success',
    poll: 'text-default',
    event: 'text-default',
    error: 'text-danger',
    complete: 'text-success',
    disconnect: 'text-muted',
}

function formatTs(at: number): string {
    return dayjs(at).format('HH:mm:ss.SSS')
}

function formatGap(gapMs: number | null): string {
    return gapMs === null ? '' : ` (+${(gapMs / 1000).toFixed(2)}s)`
}

/**
 * Dev-only floating panel (bottom-left) surfacing what the wizard sync transports are doing: which
 * mode each source runs in (SSE vs polling), when polls/events land and the gap between them, and a
 * timestamped log. Renders nothing in production builds and stays hidden until a sync source emits.
 */
export function WizardSyncDebugPanel(): JSX.Element | null {
    if (process.env.NODE_ENV !== 'development') {
        return null
    }
    return <WizardSyncDebugPanelContent />
}

function WizardSyncDebugPanelContent(): JSX.Element | null {
    const { entries, sources } = useValues(wizardSyncDebugLogic)
    const { clearSyncDebugLog } = useActions(wizardSyncDebugLogic)
    const [collapsed, setCollapsed] = useState(false)

    const sourceList = Object.values(sources)
    if (sourceList.length === 0) {
        return null
    }

    return (
        <div className="fixed bottom-2 left-2 z-[9999] max-w-lg rounded border bg-surface-primary shadow-md text-xs">
            <div className="flex items-center gap-1 px-2 py-1 border-b">
                <LemonButton
                    size="xsmall"
                    icon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                    onClick={() => setCollapsed(!collapsed)}
                    tooltip={collapsed ? 'Expand' : 'Collapse'}
                    aria-label={collapsed ? 'Expand wizard sync debug panel' : 'Collapse wizard sync debug panel'}
                />
                <span className="font-semibold">Wizard sync debug</span>
                <span className="text-muted">({pluralize(entries.length, 'event')})</span>
                <div className="flex-1" />
                <LemonButton size="xsmall" onClick={clearSyncDebugLog}>
                    Clear
                </LemonButton>
            </div>
            {!collapsed && (
                <>
                    <div className="px-2 py-1 space-y-1 border-b">
                        {sourceList.map((info) => (
                            <div key={info.source} className="flex items-center gap-2">
                                <LemonTag type={info.mode === 'polling' ? 'warning' : 'success'} size="small">
                                    {info.mode ?? '?'}
                                </LemonTag>
                                <span className="font-mono truncate max-w-40" title={info.source}>
                                    {info.source}
                                </span>
                                {info.mode === 'polling' && info.intervalMs !== null && (
                                    <span className="text-muted">~{info.intervalMs / 1000}s ±20%</span>
                                )}
                                <span className="text-muted">
                                    {pluralize(info.ticks, info.mode === 'polling' ? 'poll' : 'event')}
                                </span>
                                {info.lastAt !== null && (
                                    <span className="text-muted">
                                        last {formatTs(info.lastAt)}
                                        {formatGap(info.lastGapMs)}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                    <div className="max-h-48 overflow-y-auto overflow-x-auto px-2 py-1 font-mono whitespace-nowrap">
                        {entries.map((entry) => (
                            <div key={entry.id} className={KIND_COLORS[entry.kind]}>
                                {formatTs(entry.at)} [{entry.kind}] {entry.source}: {entry.message}
                                {formatGap(entry.gapMs)}
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
