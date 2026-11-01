import { useValues } from 'kea'
import { Suspense } from 'react'

import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'

// The modal anchors the entire replay player graph, so it loads only when a recording opens.
const SessionPlayerModal = lazyWithRetry(() =>
    import('./SessionPlayerModal').then((m) => ({ default: m.SessionPlayerModal }))
)

export function SessionPlayerModalHost(): JSX.Element | null {
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic)
    const shouldRender = useKeepMountedWhileOpen(!!activeSessionRecording)
    return shouldRender ? (
        <Suspense fallback={null}>
            <SessionPlayerModal />
        </Suspense>
    ) : null
}
