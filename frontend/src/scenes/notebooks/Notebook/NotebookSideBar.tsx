import { useActions, useValues } from 'kea'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'

export function NotebookSideBar(): JSX.Element {
    const { isNotebookSideBarShown } = useValues(navigationLogic)

    return (
        <div className={clsx('NotebookSidebar', isNotebookSideBarShown && 'NotebookSidebar--show')}>
            <div className="NotebookSidebar__content">
                <Notebook />
            </div>
        </div>
    )
}
