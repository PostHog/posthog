import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { experimentLogic } from '../experimentLogic'
import { flagBucketsOnDevice } from '../utils'

// Warns when the linked flag buckets on device, since experiment results still aggregate by person.
export function ExperimentBucketingMismatchBanner(): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)

    if (!flagBucketsOnDevice(experiment.feature_flag)) {
        return null
    }

    const flagLink = experiment.feature_flag ? (
        <Link target="_blank" to={urls.featureFlag(experiment.feature_flag.id)}>
            {experiment.feature_flag.key}
        </Link>
    ) : null

    return (
        <LemonBanner className="mb-4" type="warning">
            <div>
                <strong>The flag randomizes by device, but results are grouped by person</strong>
            </div>
            <div>
                The linked feature flag {flagLink} assigns users by device. Experiment results still group exposures and
                metrics by person, so participant counts and the sample ratio mismatch (SRM) check measure a unit the
                flag did not randomize on. Read them with care. Device bucketing is validated for flags, not yet for
                experiment analysis.
            </div>
        </LemonBanner>
    )
}
