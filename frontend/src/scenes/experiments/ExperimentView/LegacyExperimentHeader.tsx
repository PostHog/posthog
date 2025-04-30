import { Link } from '@posthog/lemon-ui'
import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

import { experimentLogic } from '../experimentLogic'
import { isLegacyExperiment } from '../utils'

export function LegacyExperimentHeader(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showNewEngineBanner =
        // We don't want to show the banner if the experiment has already started
        !experiment.start_date &&
        // We use the isLegacyExperiment to check if the experiment does _not_ have any legacy metrics added already
        // We don't want to show the banner then, as we can't automatically migrate yet. So that would be confusing,
        // as it has no effect then.
        !isLegacyExperiment(experiment) &&
        featureFlags[FEATURE_FLAGS.SHOW_NEW_EXPERIMENTATION_ENGINE_BANNER] === 'enabled'

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
