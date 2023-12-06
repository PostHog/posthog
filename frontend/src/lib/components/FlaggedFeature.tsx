import { useValues } from 'kea'
import { FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type PostHogFeatureProps = {
    /** The feature flag key(s) to check. Enabled if any flag matches. */
    flag: FeatureFlagKey | FeatureFlagKey[]
    /** What specific state or variant of feature flag needs to be active. */
    match?: string | boolean
    /** Rendered when the flag state/variant matches. */
    children: React.ReactNode | ((payload: any) => React.ReactNode)
    /** Rendered when the flag state/variant doesn't match. */
    fallback?: React.ReactNode
}

export function FlaggedFeature({ flag, match, children, fallback }: PostHogFeatureProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const flagArray = Array.isArray(flag) ? flag : [flag]
    const matchingKey =
        match === undefined
            ? flagArray.find((flag) => !!featureFlags[flag])
            : flagArray.find((flag) => (featureFlags[flag] || false) === match)

    if (matchingKey) {
        return typeof children === 'function' ? children(featureFlags[matchingKey]) : children
    } else if (fallback) {
        return <>{fallback}</>
    }

    return null
}
