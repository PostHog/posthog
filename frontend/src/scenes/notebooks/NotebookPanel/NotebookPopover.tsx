import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { notebookPopoverLogic } from 'scenes/notebooks/NotebookPanel/notebookPopoverLogic'

export function NotebookPopover(): JSX.Element {
    const { popoverVisibility, fullScreen, dropProperties } = useValues(notebookPopoverLogic)
    const { setPopoverVisibility, setFullScreen } = useActions(notebookPopoverLogic)

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

    return (
        <div>
            <div onClick={popoverVisibility === 'visible' ? () => setPopoverVisibility('hidden') : undefined} />
            <div
                onClick={popoverVisibility !== 'visible' ? () => setPopoverVisibility('visible') : undefined}
                {...dropProperties}
            />
        </div>
    )
}
