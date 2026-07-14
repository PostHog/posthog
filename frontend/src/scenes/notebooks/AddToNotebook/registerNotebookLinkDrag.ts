import { LinkDragProps, setLinkDragHook } from 'lib/lemon-ui/Link/useLinkDrag'

import { useNotebookDrag } from './DraggableToNotebook'

function useNotebookLinkDrag(href: string | undefined): LinkDragProps {
    return useNotebookDrag({ href })
}

/** Makes every `Link` with an internal href draggable into the notebook panel. */
export function registerNotebookLinkDrag(): void {
    setLinkDragHook(useNotebookLinkDrag)
}
