import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCode, IconRevert } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { editorSceneLogic } from './editorSceneLogic'
import { queryHistoryLogic } from './queryHistoryLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

function getVersionQuery(logItem: HumanizedActivityLogItem): string | null {
    const changes = logItem.unprocessed?.detail.changes
    for (const change of changes ?? []) {
        const after = change.after
        if (after && typeof after === 'object' && !Array.isArray(after)) {
            const query = (after as { query?: unknown }).query
            if (typeof query === 'string' && query.trim() !== '') {
                return query
            }
        }
    }
    return null
}

function QueryHistoryLogRow({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const queryHistoryEnabled = useFeatureFlag('SQL_EDITOR_QUERY_HISTORY')
    const { setSuggestedQueryInput } = useActions(sqlEditorLogic)
    const { closeHistoryModal } = useActions(editorSceneLogic)

    const versionQuery = getVersionQuery(logItem)

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
                    {queryHistoryEnabled && versionQuery !== null && (
                        <LemonButton
                            icon={<IconRevert />}
                            tooltip="Restore this version into the editor"
                            data-attr="sql-editor-history-restore"
                            onClick={() => {
                                setSuggestedQueryInput(versionQuery, 'query_history')
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

function QueryHistoryLogDiff({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const changes = logItem.unprocessed?.detail.changes

    return (
        <div className="flex flex-col deprecated-space-y-2 px-2 py-1">
            <div className="flex flex-col deprecated-space-y-2">
                {changes?.length ? (
                    changes.map((change, i) => {
                        return <QueryDiffViewer key={i} before={change.before} after={change.after} />
                    })
                ) : (
                    <div className="text-secondary">This item has no changes to compare</div>
                )}
            </div>
        </div>
    )
}

interface QueryDiffViewerProps {
    before: any
    after: any
}

function QueryDiffViewer({ before, after }: QueryDiffViewerProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)
    return (
        <div ref={containerRef} className="flex flex-col space-y-2 w-full">
            <MonacoDiffEditor
                key="diff-viewer"
                original={before?.query ?? ''}
                modified={after?.query ?? ''}
                language="hogQL"
                width={width}
                options={{
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    renderGutterMenu: false,
                    scrollbar: {
                        alwaysConsumeMouseWheel: false,
                    },
                }}
            />
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
    const { editingView, isHistoryModalOpen } = useValues(editorSceneLogic)
    const { closeHistoryModal } = useActions(editorSceneLogic)

    return (
        <LemonModal title="View history" isOpen={isHistoryModalOpen} onClose={closeHistoryModal} width={800}>
            <div className="ActivityLog">
                <QueryHistoryLog id={editingView?.id} />
            </div>
        </LemonModal>
    )
}
