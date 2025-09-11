import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCode } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { multitabEditorLogic } from './multitabEditorLogic'
import { queryHistoryLogic } from './queryHistoryLogic'

function QueryHistoryLogRow({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

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
    const { isHistoryModalOpen } = useValues(multitabEditorLogic)
    const { closeHistoryModal } = useActions(multitabEditorLogic)
    const { editingView } = useValues(multitabEditorLogic)

    return (
        <LemonModal title="View history" isOpen={isHistoryModalOpen} onClose={closeHistoryModal} width={800}>
            <div className="ActivityLog">
                <QueryHistoryLog id={editingView?.id} />
            </div>
        </LemonModal>
    )
}
