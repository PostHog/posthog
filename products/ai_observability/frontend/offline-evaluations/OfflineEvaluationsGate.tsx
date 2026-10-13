import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function OfflineEvaluationsGate({
    children,
    isAvailable = true,
    unavailableMessage = 'Offline evals are not available for this project.',
}: {
    children: ReactNode
    isAvailable?: boolean
    unavailableMessage?: string
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] && isAvailable ? (
        <>{children}</>
    ) : (
        <LemonBanner type="info">{unavailableMessage}</LemonBanner>
    )
}
