import { useValues } from 'kea'
import { Suspense } from 'react'

import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { composeTicketLogic } from './composeTicketLogic'

// The modal anchors the support rich text editor (tiptap and prosemirror), so it loads only when it opens.
const ComposeTicketModal = lazyWithRetry(() =>
    import('./ComposeTicketModal').then((m) => ({ default: m.ComposeTicketModal }))
)

export function ComposeTicketModalHost(): JSX.Element | null {
    const { isOpen } = useValues(composeTicketLogic)
    const shouldRender = useKeepMountedWhileOpen(isOpen)
    return shouldRender ? (
        <Suspense fallback={null}>
            <ComposeTicketModal />
        </Suspense>
    ) : null
}
