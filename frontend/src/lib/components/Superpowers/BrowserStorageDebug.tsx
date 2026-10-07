import { useState } from 'react'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { keaStorage } from 'lib/utils/keaStorage'
import { humanizeBytes } from 'lib/utils/numbers'

import { BrowserStorageSummary, summarizeBrowserStorage } from './browserStorageSummary'

function readBrowserStorage(): BrowserStorageSummary {
    let entries: [string, string][] = []
    try {
        entries = Object.keys(window.localStorage).map((key) => [key, window.localStorage.getItem(key) ?? ''])
    } catch {
        // Blocked storage reads as empty.
    }
    return summarizeBrowserStorage(entries, keaStorage.lastUsed())
}

export function BrowserStorageDebug(): JSX.Element {
    const [summary, setSummary] = useState(readBrowserStorage)

    const removeUnused = (): void => {
        const removed = keaStorage.pruneExpired()
        lemonToast.success(removed === 1 ? 'Removed 1 key' : `Removed ${removed} keys`)
        setSummary(readBrowserStorage())
    }

    const removeAll = (): void => {
        keaStorage.removeAll()
        // Mounted logics still hold the removed values in memory and would write them back.
        window.location.reload()
    }

    return (
        <div className="space-y-2">
            <p className="text-secondary mb-0">
                <span translate="no">{humanizeBytes(summary.totalBytes)}</span>
                <span> used across </span>
                <span translate="no">{summary.keyCount}</span>
                <span> keys. Browsers allow about 5 MB per site.</span>
            </p>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={removeUnused}
                    tooltip="Removes saved preferences not used in the last 30 days"
                    data-attr="browser-storage-remove-unused"
                >
                    Remove unused
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    onClick={removeAll}
                    tooltip="Removes all saved preferences and reloads the page"
                    data-attr="browser-storage-remove-all"
                >
                    Remove all saved preferences
                </LemonButton>
            </div>
            <LemonTable
                size="small"
                dataSource={summary.groups}
                rowKey="pattern"
                emptyState="Nothing is saved in this browser"
                columns={[
                    {
                        title: 'Key',
                        dataIndex: 'pattern',
                        render: (_, group) => (
                            <span className="flex items-center gap-1 font-mono text-xs break-all">
                                {group.pattern}
                                {!group.persistedByKea && <LemonTag size="small">Not cleared here</LemonTag>}
                            </span>
                        ),
                    },
                    { title: 'Keys', dataIndex: 'keyCount', align: 'right', sorter: (a, b) => a.keyCount - b.keyCount },
                    {
                        title: 'Size',
                        dataIndex: 'bytes',
                        align: 'right',
                        render: (_, group) => humanizeBytes(group.bytes),
                        sorter: (a, b) => a.bytes - b.bytes,
                    },
                    {
                        title: 'Last used',
                        dataIndex: 'lastUsed',
                        render: (_, group) =>
                            group.lastUsed === null ? (
                                <span className="text-secondary">Not recorded</span>
                            ) : (
                                <TZLabel time={dayjs(group.lastUsed)} />
                            ),
                    },
                ]}
            />
        </div>
    )
}

export function openBrowserStorageDebugModal(): void {
    LemonDialog.open({
        title: 'Browser storage',
        content: <BrowserStorageDebug />,
        primaryButton: null,
        width: 960,
    })
}
