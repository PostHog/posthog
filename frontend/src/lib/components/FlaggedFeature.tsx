import { useValues } from 'kea'
import { FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type PostHogFeatureProps = {
    flag: FeatureFlagKey
    match?: string | boolean
    children: React.ReactNode | ((payload: any) => React.ReactNode)
}

export function FlaggedFeature({ flag, match, children }: PostHogFeatureProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const flagValue = featureFlags[flag] || false

    if (match === undefined || flagValue === match) {
        return typeof children === 'function' ? children(flagValue) : children
    }

    return null
}
