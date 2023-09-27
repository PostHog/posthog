import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonButton, LemonWidget } from '@posthog/lemon-ui'

export function NotebookHistory(): JSX.Element {
    const { notebook } = useValues(notebookLogic)
    const { setShowHistory } = useActions(notebookLogic)

    return (
        <LemonWidget title="Notebook History" onClose={() => setShowHistory(false)}>
            <div className="p-2">
                <ActivityLog
                    scope={ActivityScope.NOTEBOOK}
                    // TODO: Fix typing
                    id={(notebook as any)?.id}
                    renderSideAction={() => (
                        <div>
                            <LemonButton type="primary" size="small" onClick={() => setShowHistory(false)}>
                                Revert
                            </LemonButton>
                        </div>
                    )}
                />
            </div>
        </LemonWidget>
    )
}
