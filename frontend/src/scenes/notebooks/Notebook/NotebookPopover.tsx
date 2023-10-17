import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import './NotebookPopover.scss'
import { Notebook } from './Notebook'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconFullScreen, IconChevronRight, IconOpenInNew, IconShare } from 'lib/lemon-ui/icons'
import { useEffect, useMemo, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { NotebookListMini } from './NotebookListMini'
import { notebooksModel } from '~/models/notebooksModel'
import { NotebookExpandButton, NotebookSyncInfo } from './NotebookMeta'
import { notebookLogic } from './notebookLogic'
import { urls } from 'scenes/urls'
import { NotebookPopoverDropzone } from './NotebookPopoverDropzone'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { openNotebookShareDialog } from './NotebookShare'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

export function NotebookPopoverCard(): JSX.Element | null {
    const { visibility, shownAtLeastOnce, fullScreen, selectedNotebook, initialAutofocus, droppedResource } =
        useValues(notebookPopoverLogic)
    const { setVisibility, setFullScreen, selectNotebook } = useActions(notebookPopoverLogic)
    const { createNotebook } = useActions(notebooksModel)
    const { notebook } = useValues(notebookLogic({ shortId: selectedNotebook }))
    const { activeScene } = useValues(sceneLogic)

    const showEditor = activeScene === Scene.Notebook ? visibility !== 'hidden' : shownAtLeastOnce
    const editable = visibility !== 'hidden' && !notebook?.is_template

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
                        onClick={() => setVisibility('hidden')}
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
                        onClick={() => setVisibility('hidden')}
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
    const { visibility, fullScreen, selectedNotebook, dropProperties } = useValues(notebookPopoverLogic)
    const { setVisibility, setFullScreen, setElementRef } = useActions(notebookPopoverLogic)
    const { isShowingSidebar } = useValues(notebookLogic({ shortId: selectedNotebook }))

    const ref = useRef<HTMLDivElement>(null)

    useKeyboardHotkeys(
        visibility === 'visible'
            ? {
                  escape: {
                      action: () => {
                          if (fullScreen) {
                              setFullScreen(false)
                          } else {
                              setVisibility('hidden')
                          }
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

    return (
        <div
            ref={ref}
            className={clsx(
                'NotebookPopover',
                `NotebookPopover--${visibility}`,
                fullScreen && 'NotebookPopover--full-screen',
                isShowingSidebar && 'NotebookPopover--with-sidebar'
            )}
        >
            <div
                className="NotebookPopover__backdrop"
                onClick={visibility === 'visible' ? () => setVisibility('hidden') : undefined}
            />
            <div
                className="NotebookPopover__content"
                onClick={visibility !== 'visible' ? () => setVisibility('visible') : undefined}
                {...dropProperties}
            >
                <NotebookPopoverDropzone />
                <NotebookPopoverCard />
            </div>
        </div>
    )
}
