import type { ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

export function OfflineEvaluationsGate({
    children,
    isAvailable = true,
    unavailableMessage = 'Offline evals are not available for this project.',
}: {
    children: ReactNode
    isAvailable?: boolean
    unavailableMessage?: string
}): JSX.Element {
    return isAvailable ? <>{children}</> : <LemonBanner type="info">{unavailableMessage}</LemonBanner>
}
