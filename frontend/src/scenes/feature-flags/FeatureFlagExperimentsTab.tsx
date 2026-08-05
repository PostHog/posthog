import { IconArrowRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { FeatureFlagType } from '~/types'

import { ExperimentTabContent } from 'products/experiments/frontend/experiments/ExperimentTabContent'

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
