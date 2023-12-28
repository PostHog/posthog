import './NotebookPopover.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { useEffect, useRef } from 'react'
import { notebookPopoverLogic } from 'scenes/notebooks/NotebookPanel/notebookPopoverLogic'

import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookPanelDropzone } from './NotebookPanelDropzone'

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
            </div>
        </div>
    )
}
