import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCode, IconRevert } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { QueryDiffViewer } from './components/QueryDiffViewer'
import { editorSceneLogic } from './editorSceneLogic'
import { InsightHistory } from './InsightHistory'
import { queryHistoryLogic } from './queryHistoryLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

// The query as of this edit — what "Restore" loads back into the editor.
function restorableQueryFromLog(logItem: HumanizedActivityLogItem): string | null {
    const change = logItem.unprocessed?.detail.changes?.find((c) => c.field === 'query' && extractQuery(c.after) !== '')
    return change ? extractQuery(change.after) : null
}

function QueryHistoryLogRow({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const { editingView } = useValues(editorSceneLogic)
    const { closeHistoryModal } = useActions(editorSceneLogic)
    const { setSuggestedQueryInput } = useActions(sqlEditorLogic)

    const restorableQuery = restorableQueryFromLog(logItem)

    return (
        <div className={clsx('flex flex-col px-1 py-0.5', isExpanded && 'border rounded')}>
            <div
                className={clsx('ActivityLogRow flex deprecated-space-x-2', logItem.unread && 'ActivityLogRow--unread')}
            >
                <ProfilePicture
                    showName={false}
                    user={{
                        first_name: logItem.isSystem ? logItem.name : undefined,
                        email: logItem.email ?? undefined,
                    }}
                    type={logItem.isSystem ? 'system' : 'person'}
                    size="xl"
                />
                <div className="ActivityLogRow__details flex-grow">
                    <div className="ActivityLogRow__description">{logItem.description}</div>
                    {logItem.extendedDescription && (
                        <div className="ActivityLogRow__description__extended">{logItem.extendedDescription}</div>
                    )}
                    <div className="text-secondary">
                        <TZLabel time={logItem.created_at} />
                    </div>
                </div>
                <div className="flex flex-row gap-2">
                    {restorableQuery && restorableQuery !== (editingView?.query?.query ?? '') && (
                        <LemonButton
                            size="small"
                            icon={<IconRevert />}
                            tooltip="Load this version into the editor to review and restore"
                            data-attr="sql-editor-view-history-restore"
                            onClick={(e) => {
                                e.stopPropagation()
                                setSuggestedQueryInput(restorableQuery, 'query_history')
                                // Close the modal so the restore diff in the editor is visible
                                closeHistoryModal()
                            }}
                        >
                            Restore
                        </LemonButton>
                    )}
                    <LemonButton icon={<IconCode />} onClick={() => setIsExpanded(!isExpanded)} active={isExpanded} />
                </div>
            </div>
            {isExpanded && (
                <div className="px-1 py-0.5">
                    <QueryHistoryLogDiff logItem={logItem} />
                </div>
            )}
        </div>
    )
}

function extractQuery(value: unknown): string {
    if (value && typeof value === 'object' && 'query' in value) {
        const query = (value as { query?: unknown }).query
        return typeof query === 'string' ? query : ''
    }
    return ''
}

function QueryHistoryLogDiff({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const changes = logItem.unprocessed?.detail.changes

    return (
        <div className="flex flex-col deprecated-space-y-2 px-2 py-1">
            <div className="flex flex-col deprecated-space-y-2">
                {changes?.length ? (
                    changes.map((change, i) => {
                        return (
                            <QueryDiffViewer
                                key={i}
                                original={extractQuery(change.before)}
                                modified={extractQuery(change.after)}
                            />
                        )
                    })
                ) : (
                    <div className="text-secondary">This item has no changes to compare</div>
                )}
            </div>
        </div>
    )
}

function QueryHistoryLog({ id }: { id?: number | string }): JSX.Element {
    const logic = queryHistoryLogic({ id: id as string })
    const { humanizedActivity, activityLoading, pagination } = useValues(logic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    if (!activityLoading && humanizedActivity.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <div className="text-secondary">No history found</div>
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-4">
            {activityLoading ? (
                <div className="deprecated-space-y-2">
                    <SkeletonLog />
                    <SkeletonLog />
                    <SkeletonLog />
                </div>
            ) : (
                <div className="deprecated-space-y-2">
                    {humanizedActivity.map((logItem: HumanizedActivityLogItem, index: number) => (
                        <QueryHistoryLogRow key={index} logItem={logItem} />
                    ))}
                </div>
            )}
            <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
        </div>
    )
}

export function QueryHistoryModal(): JSX.Element {
    const { editingView, editingInsight, insightLoading, isHistoryModalOpen } = useValues(editorSceneLogic)
    const { closeHistoryModal } = useActions(editorSceneLogic)

    return (
        <LemonModal
            title={editingView ? 'View history' : 'Insight history'}
            isOpen={isHistoryModalOpen}
            onClose={closeHistoryModal}
            width={800}
        >
            {editingView ? (
                <div className="ActivityLog">
                    <QueryHistoryLog id={editingView.id} />
                </div>
            ) : editingInsight || insightLoading ? (
                <InsightHistory insight={editingInsight ?? null} />
            ) : null}
        </LemonModal>
    )
}
