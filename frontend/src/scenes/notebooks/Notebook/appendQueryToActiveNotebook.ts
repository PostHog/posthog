import { Node } from '~/queries/schema'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from '~/types'

export function appendQueryToActiveNotebook(query: Node, fallback?: (query: Node) => void): void {
    // This functionn is here, and not in `notebookPopoverLogic` to avoid circular imports
    if (notebookPopoverLogic.isMounted()) {
        const { selectedNotebook } = notebookPopoverLogic.values
        const logic = notebookLogic({ shortId: selectedNotebook })

        if (!logic.isMounted()) {
            const unmount = logic.mount()
            window.setTimeout(() => {
                unmount()
            }, 1000)
        }
        logic.actions.insertAfterLastNode({
            type: NotebookNodeType.Query,
            attrs: {
                query: query,
            },
        })
        notebookPopoverLogic.actions.setVisibility('visible')
    } else if (fallback) {
        fallback(query)
    }
}
