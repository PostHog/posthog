import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconLock, IconLockOpen } from 'lib/lemon-ui/icons'
import { CSSTransition } from 'react-transition-group'
import { useEffect, useRef, useState } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import React from 'react'
import { NotebookListMini } from './NotebookListMini'
import { SCRATCHPAD_NOTEBOOK, notebooksListLogic } from './notebooksListLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './NotebookMeta'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function NotebookSideBar({ children }: { children: React.ReactElement<any> }): JSX.Element {
    const { notebookSideBarShown, fullScreen, selectedNotebook, desiredWidth } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen, selectNotebook, onResize, setElementRef } =
        useActions(notebookSidebarLogic)
    const { createNotebook } = useActions(notebooksListLogic)

    const ref = useRef<HTMLDivElement>(null)
    const [isEditable, setIsEditable] = useState(true)

    // NOTE: This doesn't work for some reason, possibly due to the way the editor is rendered
    useKeyboardHotkeys(
        notebookSideBarShown
            ? {
                  escape: {
                      action: () => {
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

    useEffect(() => {
        if (ref.current) {
            setElementRef(ref)
        }
    }, [ref.current])

    return (
        <>
            {clonedChild}
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
                <CSSTransition
                    in={notebookSideBarShown}
                    timeout={0} // Disabled this for now until we can agree on style / performance
                    mountOnEnter
                    unmountOnExit
                    classNames="NotebookSidebar-"
                >
                    <div
                        ref={ref}
                        className={clsx('NotebookSidebar', fullScreen && 'NotebookSidebar--full-screen')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            !fullScreen
                                ? {
                                      width: desiredWidth,
                                  }
                                : {}
                        }
                    >
                        <Resizer onResize={onResize} />
                        <div className="NotebookSidebar__content">
                            <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-1 border-b">
                                <span className="flex items-center gap-1 text-primary-alt">
                                    <NotebookListMini
                                        selectedNotebookId={selectedNotebook}
                                        onSelectNotebook={(notebook) => selectNotebook(notebook.short_id)}
                                        onNewNotebook={() => createNotebook()}
                                    />
                                </span>
                                <span className="flex items-center gap-1 px-1">
                                    {selectedNotebook && <NotebookSyncInfo shortId={selectedNotebook} />}

                                    <NotebookExpandButton status="primary-alt" size="small" />

                                    <LemonButton
                                        size="small"
                                        onClick={() => setIsEditable(!isEditable)}
                                        status="primary-alt"
                                        type={!isEditable ? 'primary' : undefined}
                                        icon={!isEditable ? <IconLock /> : <IconLockOpen />}
                                    />

                                    <LemonButton
                                        size="small"
                                        onClick={() => setFullScreen(!fullScreen)}
                                        status="primary-alt"
                                        icon={<IconFullScreen />}
                                    />

                                    <LemonButton
                                        size="small"
                                        onClick={() => setNotebookSideBarShown(false)}
                                        status="primary-alt"
                                        icon={<IconChevronRight />}
                                    />
                                </span>
                            </header>

                            {selectedNotebook === SCRATCHPAD_NOTEBOOK.short_id ? (
                                <LemonBanner type="info" dismissKey="notebook-sidebar-scratchpad" className="m-2">
                                    This is your scratchpad. It is only visible to you and is persisted only in this
                                    browser. It's a great place to gather ideas before turning into a saved Notebook!
                                </LemonBanner>
                            ) : null}
                            <div className="flex flex-col flex-1 overflow-y-auto p-4">
                                <Notebook key={selectedNotebook} shortId={selectedNotebook} editable={isEditable} />
                            </div>
                        </div>
                    </div>
                </CSSTransition>
            </FlaggedFeature>
        </>
    )
}
