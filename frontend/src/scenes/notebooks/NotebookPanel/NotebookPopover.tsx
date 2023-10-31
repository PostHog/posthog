import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookPopover.scss'
import { Notebook } from '../Notebook/Notebook'
import { notebookPopoverLogic } from 'scenes/notebooks/NotebookPanel/notebookPopoverLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconOpenInNew, IconShare } from 'lib/lemon-ui/icons'
import { useEffect, useMemo, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { NotebookListMini } from '../Notebook/NotebookListMini'
import { notebooksModel } from '~/models/notebooksModel'
import { NotebookExpandButton, NotebookSyncInfo } from '../Notebook/NotebookMeta'
import { notebookLogic } from '../Notebook/notebookLogic'
import { urls } from 'scenes/urls'
import { NotebookPanelDropzone } from './NotebookPanelDropzone'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { openNotebookShareDialog } from '../Notebook/NotebookShare'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

export function NotebookPopoverCard(): JSX.Element | null {
    const { popoverVisibility, shownAtLeastOnce, fullScreen, selectedNotebook, initialAutofocus, droppedResource } =
        useValues(notebookPopoverLogic)
    const { setPopoverVisibility, setFullScreen, selectNotebook } = useActions(notebookPopoverLogic)
    const { createNotebook } = useActions(notebooksModel)
    const { notebook } = useValues(notebookLogic({ shortId: selectedNotebook }))
    const { activeScene } = useValues(sceneLogic)

    const showEditor = activeScene === Scene.Notebook ? popoverVisibility !== 'hidden' : shownAtLeastOnce
    const editable = popoverVisibility !== 'hidden' && !notebook?.is_template

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        832: 'medium',
    })

    const contentWidthHasEffect = useMemo(() => fullScreen && size === 'medium', [fullScreen, size])

    if (droppedResource) {
        return null
    }

    return (
        <div ref={ref} className="NotebookPopover__content__card">
            <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-1 border-b">
                <span className="flex items-center gap-1 text-primary-alt overflow-hidden">
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
                        onClick={() => setPopoverVisibility('hidden')}
                        status="primary-alt"
                        icon={<IconOpenInNew />}
                        tooltip="View notebook outside of popover"
                        tooltipPlacement="left"
                    />
                    <LemonButton
                        size="small"
                        onClick={() => openNotebookShareDialog({ shortId: selectedNotebook })}
                        status="primary-alt"
                        icon={<IconShare />}
                        tooltip="Share notebook"
                        tooltipPlacement="left"
                    />

                    {contentWidthHasEffect && <NotebookExpandButton status="primary-alt" size="small" />}

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
                        onClick={() => setPopoverVisibility('hidden')}
                        status="primary-alt"
                        icon={<IconChevronRight />}
                        tooltip="Hide Notebook Sidebar"
                        tooltipPlacement="left"
                    />
                </span>
            </header>

            <div className="flex flex-col flex-1 overflow-y-auto px-4 py-2">
                {showEditor && (
                    <Notebook
                        key={selectedNotebook}
                        shortId={selectedNotebook}
                        editable={editable}
                        initialAutofocus={initialAutofocus}
                    />
                )}
            </div>
        </div>
    )
}

export function NotebookPopover(): JSX.Element {
    const { popoverVisibility, fullScreen, selectedNotebook, dropProperties } = useValues(notebookPopoverLogic)
    const { setPopoverVisibility, setFullScreen, setElementRef } = useActions(notebookPopoverLogic)
    const { isShowingLeftColumn } = useValues(notebookLogic({ shortId: selectedNotebook }))

    const ref = useRef<HTMLDivElement>(null)

    useKeyboardHotkeys(
        popoverVisibility === 'visible'
            ? {
                  escape: {
                      action: () => {
                          if (fullScreen) {
                              setFullScreen(false)
                          } else {
                              setPopoverVisibility('hidden')
                          }
                      },
                  },
              }
            : {},
        [popoverVisibility]
    )

    useEffect(() => {
        if (ref.current) {
            setElementRef(ref)
        }
    }, [ref.current])

    return (
        <div
            ref={ref}
            className={clsx(
                'NotebookPopover',
                `NotebookPopover--${popoverVisibility}`,
                fullScreen && 'NotebookPopover--full-screen',
                isShowingLeftColumn && 'NotebookPopover--with-sidebar'
            )}
        >
            <div
                className="NotebookPopover__backdrop"
                onClick={popoverVisibility === 'visible' ? () => setPopoverVisibility('hidden') : undefined}
            />
            <div
                className="NotebookPopover__content"
                onClick={popoverVisibility !== 'visible' ? () => setPopoverVisibility('visible') : undefined}
                {...dropProperties}
            >
                <NotebookPanelDropzone />
                <NotebookPopoverCard />
            </div>
        </div>
    )
}
