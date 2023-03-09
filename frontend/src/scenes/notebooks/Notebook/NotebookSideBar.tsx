import { useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight } from 'lib/lemon-ui/icons'

export function NotebookSideBar(): JSX.Element {
    const { isNotebookSideBarShown } = useValues(notebookSidebarLogic)

    return (
        <div className={clsx('NotebookSidebar', isNotebookSideBarShown && 'NotebookSidebar--show')}>
            <div className="NotebookSidebar__content">
                <Notebook
                    breadcrumbs={['Notebooks', 'Scratchpad']}
                    controls={
                        <>
                            <LemonButton size="small" onClick={() => alert('TODO!')} status="primary-alt" noPadding>
                                <IconFullScreen className="text-lg m-1" />
                            </LemonButton>

                            <LemonButton size="small" onClick={() => alert('TODO!')} status="primary-alt" noPadding>
                                <IconChevronRight className="text-lg" />
                            </LemonButton>
                        </>
                    }
                />
            </div>
        </div>
    )
}
