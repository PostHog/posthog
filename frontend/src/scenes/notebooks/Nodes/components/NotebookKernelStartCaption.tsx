import { useValues } from 'kea'

import { notebookBrowserKernelLogic } from '../../Notebook/browserKernel/notebookBrowserKernelLogic'
import { notebookKernelProviderLogic } from '../../Notebook/browserKernel/notebookKernelProviderLogic'

/** What a running cell is waiting on before its code executes: a kernel start or a package download. */
export function NotebookKernelStartCaption({
    notebookShortId,
    pendingKernelStart,
}: {
    notebookShortId: string
    pendingKernelStart: boolean
}): JSX.Element | null {
    const { provider } = useValues(notebookKernelProviderLogic({ shortId: notebookShortId }))
    const { progress } = useValues(notebookBrowserKernelLogic({ shortId: notebookShortId }))

    const caption =
        provider === 'browser'
            ? (progress ?? (pendingKernelStart ? 'Starting Python in your browser…' : null))
            : pendingKernelStart
              ? 'Starting compute sandbox…'
              : null
    if (!caption) {
        return null
    }
    return <div className="shrink-0 px-2 pt-1 pb-2 text-xs text-muted">{caption}</div>
}
