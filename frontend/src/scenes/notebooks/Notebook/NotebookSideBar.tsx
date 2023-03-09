import { useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'

export function NotebookSideBar(): JSX.Element {
    const { isNotebookSideBarShown } = useValues(notebookSidebarLogic)

    return (
        <div className={clsx('NotebookSidebar', isNotebookSideBarShown && 'NotebookSidebar--show')}>
            <div className="NotebookSidebar__content">
                <Notebook />
            </div>
        </div>
    )
}
