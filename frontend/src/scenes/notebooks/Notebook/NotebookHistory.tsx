import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { ActivityLogItem, ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import {
    LemonBanner,
    LemonButton,
    LemonSkeleton,
    LemonWidget,
    PaginationControl,
    ProfilePicture,
    lemonToast,
    usePagination,
} from '@posthog/lemon-ui'
import { JSONContent } from '@tiptap/core'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { TZLabel } from '@posthog/apps-common'
import { useMemo } from 'react'

const getFieldChange = (logItem: ActivityLogItem, field: string): any => {
    return logItem.detail.changes?.find((x) => x.field === field)?.after
}

function NotebookHistoryList({ onItemClick }: { onItemClick: (logItem: ActivityLogItem) => void }): JSX.Element {
    const { shortId, notebook, previewContent } = useValues(notebookLogic)

    const logic = activityLogLogic({ scope: ActivityScope.NOTEBOOK, id: shortId })
    const { activity, pagination, activityLoading } = useValues(logic)
    const paginationState = usePagination(activity.results || [], pagination)

    const activityWithChangedContent = useMemo(() => {
        return activity?.results?.filter((logItem) => {
            return !!getFieldChange(logItem, 'content') || logItem.activity === 'created'
        })
    }, [activity])

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <ul className="flex-1 overflow-y-auto p-2 space-y-px">
                {activityLoading ? (
                    <div className="space-y-px">
                        <LemonSkeleton className="w-full h-10" repeat={10} />
                    </div>
                ) : (
                    activityWithChangedContent?.map((logItem: ActivityLogItem) => {
                        const name = logItem.user.is_system ? 'System' : logItem.user.first_name
                        const isCurrent = getFieldChange(logItem, 'version') === notebook?.version
                        const changedContent = getFieldChange(logItem, 'content')
                        const isButton = changedContent && !isCurrent

                        const buttonContent = (
                            <span className="flex flex-1 gap-2 items-center p-2">
                                <ProfilePicture
                                    name={logItem.user.is_system ? logItem.user.first_name : undefined}
                                    type={logItem.user.is_system ? 'system' : 'person'}
                                    email={logItem.user.email ?? undefined}
                                    size={'md'}
                                />
                                <span className="flex-1">
                                    <b>{name}</b> {changedContent ? 'made changes' : 'created this'}
                                </span>
                                <span className="text-muted-alt">
                                    <TZLabel time={logItem.created_at} />
                                </span>
                                {isCurrent ? <span className="text-muted-alt">(Current)</span> : null}
                            </span>
                        )

                        return (
                            <li key={logItem.created_at}>
                                {isButton ? (
                                    <LemonButton
                                        fullWidth
                                        size="small"
                                        active={previewContent === changedContent}
                                        onClick={() => onItemClick(logItem)}
                                        noPadding
                                    >
                                        {buttonContent}
                                    </LemonButton>
                                ) : (
                                    buttonContent
                                )}
                            </li>
                        )
                    })
                )}
            </ul>
            <div className="p-2">
                <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
            </div>
        </div>
    )
}

export function NotebookHistory(): JSX.Element {
    const { setShowHistory, setPreviewContent } = useActions(notebookLogic)

    const onRevert = (logItem: ActivityLogItem): void => {
        const content = logItem.detail.changes?.find((x) => x.field === 'content')?.after

        if (!content) {
            lemonToast.error('Could not revert to this version')
            return
        }
        setPreviewContent(content as JSONContent)
    }

    return (
        <LemonWidget title="Notebook History" onClose={() => setShowHistory(false)}>
            <div className="NotebookHistory">
                <p className="m-3">
                    Below is the history of all persisted changes. You can select any version to view how it was at that
                    point in time and then choose to <b>revert to that version</b>, or <b>create a copy</b> of it.
                </p>

                <NotebookHistoryList onItemClick={onRevert} />
            </div>
        </LemonWidget>
    )
}

export function NotebookHistoryWarning(): JSX.Element | null {
    const { previewContent } = useValues(notebookLogic)
    const { setLocalContent, clearPreviewContent, duplicateNotebook, setShowHistory } = useActions(notebookLogic)

    if (!previewContent) {
        return null
    }

    const onCopy = (): void => {
        duplicateNotebook()
    }
    const onRevert = (): void => {
        clearPreviewContent()
        setLocalContent(previewContent)
        setShowHistory(false)
    }

    return (
        <LemonBanner type="info" className="my-4">
            <span className="flex items-center gap-2">
                <span className="flex-1">
                    <b>Hello time traveller!</b>
                    <br /> You are viewing an older revision of this Notebook. You can choose to revert to this version,
                    or create a copy of it.
                </span>

                <span className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={() => clearPreviewContent()}>
                        Cancel
                    </LemonButton>

                    <LemonButton type="primary" onClick={onRevert}>
                        Revert to this version
                    </LemonButton>
                    <LemonButton type="primary" onClick={onCopy}>
                        Create a copy
                    </LemonButton>
                </span>
            </span>
        </LemonBanner>
    )
}
