import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { MIN_NOTEBOOK_SIDEBAR_WIDTH, notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconLink } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import React from 'react'
import { NotebookListMini } from './NotebookListMini'
import { notebooksListLogic } from './notebooksListLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './NotebookMeta'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { notebookLogic } from './notebookLogic'
import { urls } from 'scenes/urls'

export function NotebookSideBar({ children }: { children: React.ReactElement<any> }): JSX.Element {
    const { notebookSideBarShown, fullScreen, selectedNotebook, desiredWidth, initialAutofocus } =
        useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen, selectNotebook, onResize, setElementRef } =
        useActions(notebookSidebarLogic)
    const { createNotebook } = useActions(notebooksListLogic)
    const { notebook } = useValues(notebookLogic({ shortId: selectedNotebook }))

    const ref = useRef<HTMLDivElement>(null)

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
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS}>
                <div
                    ref={ref}
                    className={clsx('NotebookSidebar', fullScreen && 'NotebookSidebar--full-screen')}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={
                        !fullScreen
                            ? {
                                  width: notebookSideBarShown ? desiredWidth : 0,
                                  minWidth: notebookSideBarShown ? MIN_NOTEBOOK_SIDEBAR_WIDTH : 0,
                              }
                            : {}
                    }
                >
                    <Resizer onResize={onResize} />
                    {notebookSideBarShown && (
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

                                    <LemonButton
                                        size="small"
                                        to={urls.notebook(selectedNotebook)}
                                        onClick={() => {
                                            setNotebookSideBarShown(false)
                                        }}
                                        status="primary-alt"
                                        icon={<IconLink />}
                                        tooltip="Go to Notebook"
                                        tooltipPlacement="left"
                                    />

                                    <NotebookExpandButton status="primary-alt" size="small" />

                                    <LemonButton
                                        size="small"
                                        onClick={() => setFullScreen(!fullScreen)}
                                        status="primary-alt"
                                        active={fullScreen}
                                        icon={<IconFullScreen />}
                                        tooltip="Toggle full screen"
                                        tooltipPlacement="left"
                                    />

                                    <LemonButton
                                        size="small"
                                        onClick={() => setNotebookSideBarShown(false)}
                                        status="primary-alt"
                                        icon={<IconChevronRight />}
                                        tooltip="Hide Notebook Sidebar"
                                        tooltipPlacement="left"
                                    />
                                </span>
                            </header>

                            <div className="flex flex-col flex-1 overflow-y-auto px-4 py-2">
                                <Notebook
                                    key={selectedNotebook}
                                    shortId={selectedNotebook}
                                    editable={!notebook?.is_template}
                                    initialAutofocus={initialAutofocus}
                                    showNodeSettings={false}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </FlaggedFeature>
        </>
    )
}
