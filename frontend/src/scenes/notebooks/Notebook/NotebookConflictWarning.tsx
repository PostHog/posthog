import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { notebookLogic } from './notebookLogic'

export function NotebookConflictWarning(): JSX.Element {
    const { loadNotebook } = useActions(notebookLogic)

    return (
        <div className="flex flex-col items-center text-secondary m-10">
            <h2 className="text-secondary">This Notebook has been edited elsewhere</h2>

            <p>
                It looks like someone else has been editing this content too. You will need to reload the notebook to
                see the latest version.
            </p>

            <LemonButton type="primary" onClick={loadNotebook}>
                Reload to see the latest content
            </LemonButton>
        </div>
    )
}
