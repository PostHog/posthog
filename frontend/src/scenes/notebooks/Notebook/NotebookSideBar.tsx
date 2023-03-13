import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconJournal, IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { CSSTransition } from 'react-transition-group'
import { useState } from 'react'

export function NotebookSideBar(): JSX.Element {
    const { notebookSideBarShown, fullScreen } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen } = useActions(notebookSidebarLogic)

    const [isEditable, setIsEditable] = useState(true)
    const [showCode, setShowCode] = useState(false)

    const breadcrumbs = ['Notebook', 'Scratchpad']

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
                    <div className="border rounded bg-side flex-1 shadow overflow-hidden flex flex-col h-full">
                        <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-2 border-b">
                            <span>
                                <IconJournal />{' '}
                                {breadcrumbs?.map((breadcrumb, i) => (
                                    <>
                                        {breadcrumb}
                                        {i < breadcrumbs.length - 1 && <span className="mx-1">/</span>}
                                    </>
                                ))}
                            </span>
                            <span className="flex gap-2">
                                <LemonButton
                                    size="small"
                                    onClick={() => setIsEditable(!isEditable)}
                                    status="primary-alt"
                                    type={!isEditable ? 'primary' : undefined}
                                    noPadding
                                >
                                    <div className="m-1">{!isEditable ? <IconLock /> : <IconLockOpen />}</div>
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    onClick={() => setShowCode(!showCode)}
                                    status="primary-alt"
                                    type={showCode ? 'primary' : undefined}
                                    noPadding
                                >
                                    <div className="m-1 font-mono">{'{}'}</div>
                                </LemonButton>

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
                            </span>
                        </header>
                        <Notebook id="scratchpad" editable={isEditable} sourceMode={showCode} />
                    </div>
                </div>
            </CSSTransition>
        </div>
    )
}
