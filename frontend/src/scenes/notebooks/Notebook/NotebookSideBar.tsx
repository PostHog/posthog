import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight } from 'lib/lemon-ui/icons'
import { CSSTransition } from 'react-transition-group'

export function NotebookSideBar(): JSX.Element {
    const { notebookSideBarShown, fullScreen } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen } = useActions(notebookSidebarLogic)

    return (
        <div
            className={clsx(
                'NotebookSidebar',
                notebookSideBarShown && 'NotebookSidebar--show',
                fullScreen && 'NotebookSidebar--full-screen'
            )}
        >
            <CSSTransition in={notebookSideBarShown} timeout={200} mountOnEnter unmountOnExit>
                <div className="NotebookSidebar__content">
                    <Notebook
                        breadcrumbs={['Notebooks', 'Scratchpad']}
                        controls={
                            <>
                                <LemonButton
                                    size="small"
                                    onClick={() => setFullScreen(!fullScreen)}
                                    status="primary-alt"
                                    noPadding
                                >
                                    <IconFullScreen className="text-lg m-1" />
                                </LemonButton>

                                <LemonButton
                                    size="small"
                                    onClick={() => setNotebookSideBarShown(false)}
                                    status="primary-alt"
                                    noPadding
                                >
                                    <IconChevronRight className="text-lg" />
                                </LemonButton>
                            </>
                        }
                    />
                </div>
            </CSSTransition>
        </div>
    )
}
