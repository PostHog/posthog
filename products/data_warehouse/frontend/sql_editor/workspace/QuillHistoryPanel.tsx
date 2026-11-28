import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock, IconCode, IconRevert } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { QueryDiffViewer } from 'scenes/data-warehouse/editor/components/QueryDiffViewer'
import { InsightHistory } from 'scenes/data-warehouse/editor/InsightHistory'
import { queryHistoryLogic } from 'scenes/data-warehouse/editor/queryHistoryLogic'
import { extractQuery, restorableQueryFromLog } from 'scenes/data-warehouse/editor/queryHistoryUtils'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

function initials(item: HumanizedActivityLogItem): string {
    const source = item.isSystem ? item.name : (item.email ?? item.name)
    return (source ?? '?').slice(0, 2).toUpperCase()
}

function ViewHistoryEntry({
    item,
    currentQuery,
}: {
    item: HumanizedActivityLogItem
    currentQuery: string
}): JSX.Element {
    const [showChanges, setShowChanges] = useState(false)
    const { setSuggestedQueryInput } = useActions(sqlEditorLogic)
    const restorableQuery = restorableQueryFromLog(item)
    const changes = item.unprocessed?.detail.changes ?? []

    return (
        <li className="flex flex-col gap-2 rounded-md p-2 hover:bg-fill-hover">
            <div className="flex items-start gap-2">
                <Avatar size="sm">
                    <AvatarFallback>{initials(item)}</AvatarFallback>
                </Avatar>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <Text size="xs" className="m-0">
                        {item.description}
                    </Text>
                    <Text size="xs" className="m-0 text-muted-foreground">
                        <TZLabel time={item.created_at} />
                    </Text>
                </div>
            </div>
            <div className="flex flex-wrap gap-1 ps-8">
                {restorableQuery && restorableQuery !== currentQuery ? (
                    <Button
                        variant="outline"
                        size="sm"
                        tooltip="Load this version into the editor to review and restore"
                        onClick={() => setSuggestedQueryInput(restorableQuery, 'query_history')}
                        data-attr="sql-editor-view-history-restore"
                    >
                        <IconRevert />
                        Restore
                    </Button>
                ) : null}
                {changes.length > 0 ? (
                    <Button size="sm" onClick={() => setShowChanges(!showChanges)} aria-expanded={showChanges}>
                        <IconCode />
                        {showChanges ? 'Hide changes' : 'Show changes'}
                    </Button>
                ) : null}
            </div>
            {showChanges ? (
                <div className="flex flex-col gap-2">
                    {changes.map((change, index) => (
                        <QueryDiffViewer
                            key={index}
                            original={extractQuery(change.before)}
                            modified={extractQuery(change.after)}
                        />
                    ))}
                </div>
            ) : null}
        </li>
    )
}

function ViewHistory({ viewId, currentQuery }: { viewId: string; currentQuery: string }): JSX.Element {
    const { humanizedActivity, activityLoading } = useValues(queryHistoryLogic({ id: viewId }))

    if (activityLoading) {
        return (
            <div className="flex flex-col gap-2 p-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
            </div>
        )
    }
    if (humanizedActivity.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>No changes yet</EmptyTitle>
                    <EmptyDescription>
                        Each update to this view shows up here, with a way to restore it.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {humanizedActivity.map((item, index) => (
                <ViewHistoryEntry key={index} item={item} currentQuery={currentQuery} />
            ))}
        </ul>
    )
}

export function QuillHistoryPanel(): JSX.Element {
    const { editingView, editingInsight, insightLoading } = useValues(sqlEditorLogic)

    return (
        <div className="h-full min-h-0 overflow-y-auto scroll-mask-y-4 scroll-py-4 p-2">
            {editingView ? (
                <ViewHistory viewId={editingView.id} currentQuery={editingView.query?.query ?? ''} />
            ) : editingInsight || insightLoading ? (
                <InsightHistory insight={editingInsight ?? null} />
            ) : (
                <Empty className="h-full">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconClock />
                        </EmptyMedia>
                        <EmptyTitle>No history for a new query</EmptyTitle>
                        <EmptyDescription>
                            Save this query as a view or an insight, and every later change shows up here.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )}
        </div>
    )
}
