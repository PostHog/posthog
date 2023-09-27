import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonBanner, LemonButton, LemonWidget, lemonToast } from '@posthog/lemon-ui'
import { JSONContent } from '@tiptap/core'

export function NotebookHistory(): JSX.Element {
    const { notebook } = useValues(notebookLogic)
    const { setShowHistory, setPreviewContent } = useActions(notebookLogic)

    const onRevert = (logItem: HumanizedActivityLogItem): void => {
        const content = logItem.activity.detail.changes?.find((x) => x.field === 'content')?.before

        if (!content) {
            lemonToast.error('Could not revert to this version')
            return
        }
        setPreviewContent(content as JSONContent)
        // setShowHistory(false)
    }

    return (
        <LemonWidget title="Notebook History" onClose={() => setShowHistory(false)}>
            <div className="NotebookHistory">
                <ActivityLog
                    scope={ActivityScope.NOTEBOOK}
                    // TODO: Fix typing
                    id={(notebook as any)?.id}
                    renderSideAction={(logItem) => (
                        <div>
                            <LemonButton type="primary" size="small" onClick={() => onRevert(logItem)}>
                                Revert
                            </LemonButton>
                        </div>
                    )}
                />
            </div>
        </LemonWidget>
    )
}

export function NotebookHistoryWarning(): JSX.Element | null {
    const { previewContent } = useValues(notebookLogic)
    const { clearPreviewContent } = useActions(notebookLogic)

    if (!previewContent) {
        return null
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

                    <LemonButton type="primary">Revert to this version</LemonButton>
                    <LemonButton type="primary">Create a copy</LemonButton>
                </span>
            </span>
        </LemonBanner>
    )
}
