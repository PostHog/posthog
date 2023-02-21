import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type PostHogFeatureProps = {
    flag: typeof FEATURE_FLAGS[keyof typeof FEATURE_FLAGS]
    match?: string | boolean
    children: React.ReactNode | ((payload: any) => React.ReactNode)
}

export function FlaggedFeature({ flag, match, children }: PostHogFeatureProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const flagValue = featureFlags[flag]

    if (match === undefined || flagValue === match) {
        return typeof children === 'function' ? children(flagValue) : children
    }

    return null
}
