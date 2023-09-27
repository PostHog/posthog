import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonButton, LemonWidget, lemonToast } from '@posthog/lemon-ui'
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
        setPreviewContent(content as JSONContent, true)
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
