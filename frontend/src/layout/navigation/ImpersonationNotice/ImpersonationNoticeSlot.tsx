import { useValues } from 'kea'
import { Suspense, useEffect, useState } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

// Only staff who impersonate a user see the notice, so everyone else skips the chunk and react-draggable.
const ImpersonationNotice = lazyWithRetry(() =>
    import('./ImpersonationNotice').then(({ ImpersonationNotice }) => ({ default: ImpersonationNotice }))
)

export function ImpersonationNoticeSlot(): JSX.Element | null {
    const { user } = useValues(userLogic)
    // Stays true after the session ends, so the notice can still show its expired-session overlay.
    const [wasImpersonated, setWasImpersonated] = useState(false)

    useEffect(() => {
        if (user?.is_impersonated) {
            setWasImpersonated(true)
        }
    }, [user?.is_impersonated])

    if (!wasImpersonated) {
        return null
    }

    return (
        <ErrorBoundary>
            <Suspense fallback={null}>
                <ImpersonationNotice />
            </Suspense>
        </ErrorBoundary>
    )
}
