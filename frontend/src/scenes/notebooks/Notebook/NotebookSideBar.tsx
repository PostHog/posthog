import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookSideBar.scss'
import { Notebook } from './Notebook'
import { notebookSidebarLogic } from 'scenes/notebooks/Notebook/notebookSidebarLogic'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconJournal, IconLock, IconLockOpen, IconPlus } from 'lib/lemon-ui/icons'
import { CSSTransition } from 'react-transition-group'
import { useState } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

export function NotebookSideBar(): JSX.Element {
    const { notebookSideBarShown, fullScreen, notebooks, selectedNotebook } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, setFullScreen, selectNotebook, createNotebook } = useActions(notebookSidebarLogic)

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

    return (
        <div
            className={clsx(
                'NotebookSidebar',
                notebookSideBarShown && 'NotebookSidebar--show',
                fullScreen && 'NotebookSidebar--full-screen'
            )}
        >
            <CSSTransition in={notebookSideBarShown} timeout={200} mountOnEnter unmountOnExit>
                <div className="NotebookSidebar__floater">
                    <div className="NotebookSidebar__content">
                        <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-2 border-b">
                            <span className="flex items-center gap-1 text-primary-alt">
                                <LemonButtonWithDropdown
                                    status="primary-alt"
                                    dropdown={{
                                        overlay: (
                                            <>
                                                {notebooks.map((notebook) => (
                                                    <LemonButton
                                                        key={notebook}
                                                        status="stealth"
                                                        onClick={() => {
                                                            selectNotebook(notebook)
                                                        }}
                                                        fullWidth
                                                    >
                                                        {notebook || <i>Untitled</i>}
                                                    </LemonButton>
                                                ))}
                                                <LemonButton
                                                    icon={<IconPlus />}
                                                    onClick={() => createNotebook('Untitled')}
                                                >
                                                    New notebook
                                                </LemonButton>
                                            </>
                                        ),
                                        placement: 'right-start',
                                        fallbackPlacements: ['left-start'],
                                        closeParentPopoverOnClickInside: true,
                                    }}
                                    size="small"
                                    icon={<IconJournal />}
                                    sideIcon={null}
                                >
                                    <span className="font-semibold">{selectedNotebook}</span>
                                </LemonButtonWithDropdown>
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
                        <Notebook
                            key={selectedNotebook}
                            id={selectedNotebook}
                            editable={isEditable}
                            sourceMode={showCode}
                        />
                    </div>
                </div>
            </CSSTransition>
        </div>
    )
}
