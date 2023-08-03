import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookPopover.scss'
import { Notebook } from './Notebook'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconLink } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { NotebookListMini } from './NotebookListMini'
import { notebooksListLogic } from './notebooksListLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './NotebookMeta'
import { notebookLogic } from './notebookLogic'
import { urls } from 'scenes/urls'

export function NotebookPopover(): JSX.Element {
    const { visibility, shownAtLeastOnce, fullScreen, selectedNotebook, initialAutofocus, dropListeners } =
        useValues(notebookPopoverLogic)
    const { setVisibility, setFullScreen, selectNotebook, setElementRef } = useActions(notebookPopoverLogic)
    const { createNotebook } = useActions(notebooksListLogic)
    const { notebook } = useValues(notebookLogic({ shortId: selectedNotebook }))

    const ref = useRef<HTMLDivElement>(null)

    // NOTE: This doesn't work for some reason, possibly due to the way the editor is rendered
    useKeyboardHotkeys(
        visibility === 'visible'
            ? {
                  escape: {
                      action: () => {
                          setFullScreen(false)
                      },
                  },
              }
            : {},
        [visibility]
    )

    useEffect(() => {
        if (ref.current) {
            setElementRef(ref)
        }
    }, [ref.current])

    const isEditable = visibility !== 'hidden' && !notebook?.is_template

    return (
        <div
            ref={ref}
            className={clsx(
                'NotebookPopover',
                `NotebookPopover--${visibility}`,
                fullScreen && 'NotebookPopover--full-screen'
            )}
        >
            <div
                className="NotebookPopover__backdrop"
                onClick={visibility === 'visible' ? () => setVisibility('hidden') : undefined}
            />
            <div
                className="NotebookPopover__content"
                onClick={visibility !== 'visible' ? () => setVisibility('visible') : undefined}
                {...dropListeners}
            >
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
                            onClick={() => setVisibility('hidden')}
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
                            onClick={() => setVisibility('hidden')}
                            status="primary-alt"
                            icon={<IconChevronRight />}
                            tooltip="Hide Notebook Sidebar"
                            tooltipPlacement="left"
                        />
                    </span>
                </header>

                <div className="flex flex-col flex-1 overflow-y-auto px-4 py-2">
                    {shownAtLeastOnce && (
                        <Notebook
                            key={selectedNotebook}
                            shortId={selectedNotebook}
                            editable={isEditable}
                            initialAutofocus={initialAutofocus}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
