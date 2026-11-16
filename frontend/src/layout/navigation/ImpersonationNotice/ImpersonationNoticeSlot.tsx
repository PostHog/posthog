import { useValues } from 'kea'
import { Suspense, useEffect, useState } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

// Only staff who impersonate a user see the notice, so everyone else skips the chunk and react-draggable.
const ImpersonationNotice = lazyWithRetry(() =>
    import('./ImpersonationNotice').then(({ ImpersonationNotice }) => ({ default: ImpersonationNotice }))
)

export function ImpersonationNoticeSlot(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const isImpersonated = !!user?.is_impersonated
    // Stays true after the session ends, so the notice can still show its expired-session overlay.
    const [wasImpersonated, setWasImpersonated] = useState(isImpersonated)

    useEffect(() => {
        if (isImpersonated) {
            setWasImpersonated(true)
        }
    }, [isImpersonated])

    if (!isImpersonated && !wasImpersonated) {
        return null
    }

    return (
        <ErrorBoundary>
            <ChunkLoadErrorBoundary>
                <Suspense fallback={null}>
                    <ImpersonationNotice />
                </Suspense>
            </ChunkLoadErrorBoundary>
        </ErrorBoundary>
    )
}
