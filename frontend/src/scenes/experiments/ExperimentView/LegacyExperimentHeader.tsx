import { Link } from '@posthog/lemon-ui'
import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

import { experimentLogic } from '../experimentLogic'

export function LegacyExperimentHeader(): JSX.Element {
    const { hasMetrics } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showNewEngineBanner =
        !hasMetrics && featureFlags[FEATURE_FLAGS.SHOW_NEW_EXPERIMENTATION_ENGINE_BANNER] === 'enabled'

    return (
        <>
            {showNewEngineBanner && (
                <LemonBanner type="info" className="mb-4" dismissKey="experiment-view-new-query-runner-banner">
                    New experimentation engine and improved UI available in beta! Would you like to try it? Read more
                    about it
                    <Link to="https://posthog.com/docs/experiments/new-experimentation-engine"> here</Link>.
                </LemonBanner>
            )}
            <div className="w-1/2 mt-8 xl:mt-0">
                <DataCollection />
            </div>
        </>
    )
}
