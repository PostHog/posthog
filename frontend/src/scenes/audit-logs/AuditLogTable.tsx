import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

export interface AuditLogTableRowProps {
    logItem: HumanizedActivityLogItem
}

export function AuditLogTableHeader(): JSX.Element {
    return (
        <div className="grid grid-cols-12 gap-4 py-3 px-4 bg-accent-3000 border-b border-border font-semibold text-sm text-muted-alt">
            <div className="col-span-4">Description</div>

            <div className="col-span-2">User</div>

            <div className="col-span-2">Action</div>

            <div className="col-span-2">Scope</div>

            <div className="col-span-1">Timestamp</div>

            <div className="col-span-1" />
        </div>
    )
}

export function AuditLogTableRow({ logItem }: AuditLogTableRowProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const unprocessed = logItem.unprocessed

    return (
        <div className="border-b border-border last:border-b-0">
            <div
                className="grid grid-cols-12 gap-4 py-3 px-4 hover:bg-accent-3000 items-center text-sm cursor-pointer"
                onClick={() => setExpanded(!expanded)}
                data-attr="audit-log-row"
            >
                <div className="col-span-4">
                    <div className="truncate [&_div]:inline [&_div]:mr-1">
                        {typeof logItem.description === 'string'
                            ? logItem.description
                            : logItem.description || 'No description'}
                    </div>
                </div>

                <div className="col-span-2">
                    <ProfilePicture
                        showName={true}
                        user={{
                            first_name: logItem.isSystem ? 'PostHog' : logItem.name,
                            email: logItem.email ?? undefined,
                        }}
                        type={logItem.isSystem ? 'system' : 'person'}
                        size="md"
                    />
                </div>

                <div className="col-span-2">
                    <span className="capitalize">{unprocessed?.activity || 'Unknown'}</span>
                </div>

                <div className="col-span-2">
                    <span className="inline-block px-2 py-1 bg-accent-3000 rounded">
                        {unprocessed?.scope ? humanizeScope(unprocessed.scope, true) : 'Unknown'}
                    </span>
                </div>

                <div className="col-span-1 text-muted text-xs">
                    <TZLabel time={logItem.created_at} />
                </div>

                <div className="col-span-1 flex justify-end">
                    <button
                        className="text-muted-alt hover:text-default p-1 rounded hover:bg-accent-3000"
                        onClick={(e) => {
                            e.stopPropagation()
                            setExpanded(!expanded)
                        }}
                        aria-label={expanded ? 'Collapse row' : 'Expand row'}
                        data-attr="audit-log-expand-button"
                    >
                        {expanded ? <IconCollapse /> : <IconExpand />}
                    </button>
                </div>
            </div>

            {expanded && (
                <div className="bg-surface-secondary border-t border-border">
                    <div className="px-6 py-4">
                        {unprocessed && (
                            <>
                                <div className="mb-6">
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div className="space-y-3">
                                            <div>
                                                <div className="text-xs font-medium text-muted-alt uppercase tracking-wider mb-1">
                                                    Description
                                                </div>
                                                <div className="text-sm text-default [&_div]:inline [&_div]:mr-1">
                                                    {logItem.description}
                                                </div>
                                            </div>
                                            {logItem.extendedDescription && (
                                                <div>
                                                    <div className="text-xs font-medium text-muted-alt uppercase tracking-wider mb-1">
                                                        Extended Description
                                                    </div>
                                                    <div className="text-sm text-default [&_div]:inline [&_div]:mr-1">
                                                        {logItem.extendedDescription}
                                                    </div>
                                                </div>
                                            )}
                                            {unprocessed.item_id && (
                                                <div>
                                                    <div className="text-xs font-medium text-muted-alt uppercase tracking-wider mb-1">
                                                        Item ID
                                                    </div>
                                                    <div className="text-sm text-default">{unprocessed.item_id}</div>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div>
                                    <ActivityDetailsSection logItem={logItem} />
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}
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
                          label: 'Extended Description',
                          tooltip: 'Some activities have a more detailed description that is not shown when collapsed.',
                          content: <div className="[&_div]:inline [&_div]:mr-1">{logItem.extendedDescription}</div>,
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
