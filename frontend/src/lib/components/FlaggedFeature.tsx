import { useValues } from 'kea'

import { FeatureFlagKey } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

export type PostHogFeatureProps = {
    flag: FeatureFlagKey
    /** What specific state or variant of feature flag needs to be active. */
    match?: string | boolean
    /** Rendered when the flag state/variant matches. */
    children: React.ReactNode | ((flagValue: string | boolean, payload: any) => React.ReactNode)
    /** Rendered when the flag state/variant doesn't match. */
    fallback?: React.ReactNode
}

export function FlaggedFeature({ flag, match, children, fallback }: PostHogFeatureProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const showFlaggedFeature = useFeatureFlag('FLAGGED_FEATURE_INDICATOR')
    const flagValue = featureFlags[flag] || false
    const payload = getFeatureFlagPayload(flag)
    const doesFlagMatch = match === undefined ? !!flagValue : flagValue === match

    if (doesFlagMatch) {
        const childContent = typeof children === 'function' ? children(flagValue, payload) : children
        if (showFlaggedFeature) {
            // NOTE: this isn't perfect adding a div as it makes it an impure wrapper but for debugging in most cases its good enough for now
            return (
                <div className="relative outline-2 outline-offset-2 outline-dashed outline-red-200 rounded group">
                    <div className="absolute right-0 -top-8 bg-red-200 text-red-800 p-1 rounded text-xs font-medium opacity-0 group-hover:opacity-100 transition-all duration-300 pointer-events-none group-hover:pointer-events-auto">
                        Flagged feature: {flag} - {doesFlagMatch ? 'match' : 'no match'}
                    </div>
                    {childContent}
                </div>
            )
        }
        return childContent
    } else if (fallback) {
        return <>{fallback}</>
    }

    return null
}
