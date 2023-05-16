import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { CSSTransition } from 'react-transition-group'
import { useState } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import React from 'react'
import { NotebookListMini } from './NotebookListMini'
import { notebooksListLogic } from './notebooksListLogic'

export function NotebookSideBar({ children }: { children: React.ReactElement<any> }): JSX.Element {
    const { notebookSideBarShown, fullScreen, selectedNotebook } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen, selectNotebook } = useActions(notebookSidebarLogic)
    const { createNotebook } = useActions(notebooksListLogic)

    const [isEditable, setIsEditable] = useState(true)
    const [showCode, setShowCode] = useState(false)

    // NOTE: This doesn't work for some reason, possibly due to the way the editor is rendered
    useKeyboardHotkeys(
        notebookSideBarShown
            ? {
                  escape: {
                      action: function () {
                          setFullScreen(false)
                      },
                  },
              }
            : {},
        [notebookSideBarShown]
    )

    const clonedChild = React.cloneElement(children, {
        style: fullScreen ? { display: 'none', visibility: 'hidden' } : {},
    })

    return (
        <>
            {clonedChild}
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
                <CSSTransition
                    in={notebookSideBarShown}
                    timeout={200}
                    mountOnEnter
                    unmountOnExit
                    classNames="NotebookSidebar-"
                >
                    <div className={clsx('NotebookSidebar', fullScreen && 'NotebookSidebar--full-screen')}>
                        <div className="NotebookSidebar__content">
                            <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-1 border-b">
                                <span className="flex items-center gap-1 text-primary-alt">
                                    <NotebookListMini
                                        selectedNotebookId={selectedNotebook}
                                        onSelectNotebook={(notebook) => selectNotebook(notebook.id)}
                                        onNewNotebook={() => createNotebook()}
                                    />
                                </span>
                                <span className="flex gap-1 px-1">
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
                            <Notebook
                                key={selectedNotebook}
                                id={selectedNotebook}
                                editable={isEditable}
                                sourceMode={showCode}
                            />
                        </div>
                    </div>
                </CSSTransition>
            </FlaggedFeature>
        </>
    )
}
