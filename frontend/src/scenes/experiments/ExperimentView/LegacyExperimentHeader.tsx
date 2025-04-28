import { Link } from '@posthog/lemon-ui'
import { LemonBanner } from '@posthog/lemon-ui'
import { FEATURE_FLAGS } from 'lib/constants'
import { PostHogFeature } from 'posthog-js/react'
import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

export function LegacyExperimentHeader(): JSX.Element {
    return (
        <>
            <PostHogFeature flag={FEATURE_FLAGS.SHOW_NEW_EXPERIMENTATION_ENGINE_BANNER} match="enabled">
                <LemonBanner type="info" className="mb-4" dismissKey="experiment-view-new-query-runner-banner">
                    New experimentation engine and improved UI available in beta! Would you like to try it? Read more
                    about it
                    <Link to="https://posthog.com/docs/experiments/new-experimentation-engine"> here</Link>.
                </LemonBanner>
            </PostHogFeature>
            <div className="w-1/2 mt-8 xl:mt-0">
                <DataCollection />
            </div>
        </>
    )
}
