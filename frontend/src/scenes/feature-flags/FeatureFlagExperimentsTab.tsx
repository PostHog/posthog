import { IconArrowRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ExperimentTabContent } from 'scenes/experiments/ExperimentTabContent'
import { urls } from 'scenes/urls'

import type { FeatureFlagType } from '~/types'

export function ExperimentsTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <ExperimentTabContent
            featureFlag={featureFlag}
            multipleExperimentsBannerMessage={
                <>
                    Showing experiments associated with this feature flag.{' '}
                    <Link to={urls.experiments()}>
                        See all experiments <IconArrowRight />
                    </Link>
                </>
            }
        />
    )
}
