import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

export interface AuditLogTableProps {
    logItems: HumanizedActivityLogItem[]
    pagination?: PaginationManual
}

const columns: LemonTableColumns<HumanizedActivityLogItem> = [
    {
        title: 'Description',
        dataIndex: 'description',
        key: 'description',
        className: 'max-w-80',
        render: (description) => (
            <span className="[&_*]:inline whitespace-nowrap overflow-hidden text-ellipsis">
                {typeof description === 'string' ? description : description || 'No description'}
            </span>
        ),
        width: '40%',
    },
    {
        title: 'User',
        key: 'user',
        render: (_, logItem) => (
            <ProfilePicture
                showName={true}
                user={{
                    first_name: logItem.isSystem ? 'PostHog' : logItem.name,
                    email: logItem.email ?? undefined,
                }}
                type={logItem.isSystem ? 'system' : 'person'}
                size="md"
            />
        ),
        width: '20%',
    },
    {
        title: 'Activity',
        key: 'action',
        render: (_, logItem) => <span className="capitalize">{logItem.unprocessed?.activity || 'Unknown'}</span>,
        width: '20%',
    },
    {
        title: 'Scope',
        key: 'scope',
        render: (_, logItem) => (
            <span className="inline-block">
                {logItem.unprocessed?.scope ? humanizeScope(logItem.unprocessed.scope, true) : 'Unknown'}
            </span>
        ),
        width: '20%',
    },
    {
        title: 'Time',
        key: 'time',
        render: (_, logItem) => <TZLabel time={logItem.created_at} />,
        width: '10%',
    },
]

export function AuditLogTable({ logItems, pagination }: AuditLogTableProps): JSX.Element {
    const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

    const toggleRowExpansion = (_: HumanizedActivityLogItem, index: number): void => {
        setExpandedRows((prev) => {
            const newSet = new Set(prev)
            if (newSet.has(index)) {
                newSet.delete(index)
            } else {
                newSet.add(index)
            }
            return newSet
        })
    }

    const isRowExpanded = (_: HumanizedActivityLogItem, index: number): boolean => {
        return expandedRows.has(index)
    }

    return (
        <LemonTable
            columns={columns}
            dataSource={logItems}
            expandable={{
                expandedRowRender: (logItem) => <ExpandedRowContent logItem={logItem} />,
                rowExpandable: () => true,
                isRowExpanded: (logItem, index) => (isRowExpanded(logItem, index) ? 1 : 0),
                onRowExpand: (logItem, index) => toggleRowExpansion(logItem, index),
                onRowCollapse: (logItem, index) => toggleRowExpansion(logItem, index),
            }}
            onRow={(logItem, index) => ({
                onClick: (e) => {
                    if ((e.target as HTMLElement).closest('.LemonTable__toggle')) {
                        return
                    }
                    toggleRowExpansion(logItem, index)
                },
                style: { cursor: 'pointer' },
            })}
            pagination={pagination}
            data-attr="audit-log-table"
        />
    )
}

function ExpandedRowContent({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const unprocessed = logItem.unprocessed

    if (!unprocessed) {
        return <div className="p-4 text-muted">No additional details available</div>
    }

    return (
        <div className="p-4 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-3">
                    <div>
                        <div className="text-[11px] font-medium text-muted-alt uppercase tracking-wider mb-1">
                            Description
                        </div>
                        <div className="text-[13px] text-default">{logItem.description}</div>
                    </div>
                    {logItem.extendedDescription && (
                        <div>
                            <div className="text-[11px] font-medium text-muted-alt uppercase tracking-wider mb-1">
                                Extended Description
                            </div>
                            <div className="text-[13px] text-default">{logItem.extendedDescription}</div>
                        </div>
                    )}
                    {unprocessed.item_id && (
                        <div>
                            <div className="text-[11px] font-medium text-muted-alt uppercase tracking-wider mb-1">
                                Item ID
                            </div>
                            <div className="text-[13px] text-default">{unprocessed.item_id}</div>
                        </div>
                    )}
                </div>
            </div>

            <ActivityDetailsSection logItem={logItem} />
        </div>
    )
}

type ActivityLogTabs = 'extended description' | 'diff' | 'raw'

const ActivityDetailsSection = ({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element => {
    const [activeTab, setActiveTab] = useState<ActivityLogTabs>('diff')

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(key) => setActiveTab(key as ActivityLogTabs)}
            data-attr="audit-log-details-tabs"
            tabs={[
                logItem.extendedDescription
                    ? {
                          key: 'extended description',
                          label: 'Extended description',
                          tooltip: 'Some activities have a more detailed description that is not shown when collapsed.',
                          content: <div>{logItem.extendedDescription}</div>,
                      }
                    : false,
                {
                    key: 'diff',
                    label: 'Diff',
                    tooltip:
                        'Show the diff of the changes made to the item. Each activity item could have more than one change.',
                    content: <ActivityLogDiff logItem={logItem} />,
                },
                {
                    key: 'raw',
                    label: 'Raw',
                    tooltip: 'Show the raw data of the activity item.',
                    content: (
                        <div className="bg-surface-primary p-2 rounded border border-border text-sm">
                            <pre>{JSON.stringify(logItem.unprocessed, null, 2)}</pre>
                        </div>
                    ),
                },
            ]}
        />
    )
}

const ActivityLogDiff = ({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element => {
    const changes = logItem.unprocessed?.detail.changes

    return (
        <div className="flex flex-col space-y-2 px-2 py-1">
            <div className="flex flex-col space-y-2">
                {changes?.length ? (
                    changes.map((change, i) => {
                        return (
                            <JsonDiffViewer
                                key={i}
                                field={change.field || ''}
                                before={change.before}
                                after={change.after}
                            />
                        )
                    })
                ) : (
                    <div className="text-muted">This item has no changes to compare</div>
                )}
            </div>
        </div>
    )
}

interface JsonDiffViewerProps {
    field: string
    before: any
    after: any
}

const JsonDiffViewer = ({ field, before, after }: JsonDiffViewerProps): JSX.Element => {
    const beforeStr = JSON.stringify(before, null, 2)
    const afterStr = JSON.stringify(after, null, 2)

    if (beforeStr === afterStr) {
        return (
            <div className="border rounded p-2 bg-surface-primary">
                <div className="font-medium text-sm mb-1">{field}</div>
                <div className="text-muted text-xs">No changes detected</div>
            </div>
        )
    }

    return (
        <div className="border rounded bg-surface-primary">
            <div className="font-medium text-sm p-2">{field}</div>
            <MonacoDiffEditor
                original={beforeStr}
                value={afterStr}
                modified={afterStr}
                language="json"
                options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    renderSideBySide: true,
                    hideUnchangedRegions: {
                        enabled: true,
                        contextLineCount: 3,
                        minimumLineCount: 3,
                        revealLineCount: 20,
                    },
                    diffAlgorithm: 'advanced',
                }}
            />
        </div>
    )
}
