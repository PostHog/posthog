import { useActions } from 'kea'
import './NotebookConflictOverlay.scss'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from './notebookLogic'

export function NotebookConflictOverlay(): JSX.Element {
    const { loadNotebook } = useActions(notebookLogic)

    return (
        <div className="NotebookConflictOverlay space-y-2">
            <div className="truncate text-default font-normal">
                It looks like someone else has been editing this content too. You will need to reload the notebook to
                see the latest version.
            </div>
            <LemonButton type="primary" onClick={loadNotebook}>
                Reload
            </LemonButton>
        </div>
    )
}
