import { useValues } from 'kea'
import { FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type PostHogFeatureProps = {
    flag: FeatureFlagKey
    /** What specific state or variant of feature flag needs to be active. */
    match?: string | boolean
    /** Rendered when the flag state/variant matches. */
    children: React.ReactNode | ((payload: any) => React.ReactNode)
    /** Rendered when the flag state/variant doesn't match. */
    fallback?: React.ReactNode
}

export function FlaggedFeature({ flag, match, children, fallback }: PostHogFeatureProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const flagValue = featureFlags[flag] || false
    const doesFlagMatch = match === undefined ? !!flagValue : flagValue === match

    if (doesFlagMatch) {
        return typeof children === 'function' ? children(flagValue) : children
    } else if (fallback) {
        return <>{fallback}</>
    }

    return null
}
