import { useActions, useValues } from 'kea'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import clsx from 'clsx'
import { Notebook } from 'lib/components/Notebook/Notebook'
import './NotebookSideBar.scss'

export function NotebookSideBar(): JSX.Element {
    const { isNotebookSideBarShown } = useValues(navigationLogic)
    const { hideNotebookSideBarMobile } = useActions(navigationLogic)

    return (
        <div className={clsx('Notebook__sidebar', 'Notebook__layout', !isNotebookSideBarShown && 'Notebook--hidden')}>
            <div className={'Notebook__slider'}>
                <div className="Notebook__content">
                    <Notebook />
                </div>
            </div>
            <div className="Notebook__overlay" onClick={hideNotebookSideBarMobile} />
        </div>
    )
}
