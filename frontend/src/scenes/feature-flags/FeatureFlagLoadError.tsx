import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'

/**
 * Shown when the flag could not be loaded for a reason that says nothing about whether it exists.
 * A live flag must never read as deleted, so this offers a retry instead of the not-found screen.
 */
export function FeatureFlagLoadError({ id }: FeatureFlagLogicProps): JSX.Element {
    const logic = featureFlagLogic({ id })
    const { featureFlagLoading } = useValues(logic)
    const { loadFeatureFlag } = useActions(logic)

    return (
        <div className="p-4">
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    loading: featureFlagLoading,
                    onClick: () => loadFeatureFlag(),
                }}
            >
                We couldn't load this feature flag. Check your connection, then try again.
            </LemonBanner>
        </div>
    )
}
