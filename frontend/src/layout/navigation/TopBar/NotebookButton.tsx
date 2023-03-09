import { IconJournal } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'

export function NotebookButton(): JSX.Element {
    const { notebookSideBarShown } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown } = useActions(notebookSidebarLogic)

    return (
        <div
            className="h-10 items-center flex cursor-pointer text-primary-alt text-2xl"
            onClick={() => setNotebookSideBarShown(!notebookSideBarShown)}
        >
            <IconJournal />
        </div>
    )
}
