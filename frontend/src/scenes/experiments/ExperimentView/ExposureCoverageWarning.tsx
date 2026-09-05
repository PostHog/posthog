import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { experimentLogic } from '../experimentLogic'

/**
 * Surfaces exposures lost to failed flag evaluations: people who called the flag and only
 * ever got an error back. The backend only emits `exposure_coverage` once the errored share
 * clears the threshold on a large enough sample, so presence of the field is the gate.
 */
export function ExposureCoverageWarning(): JSX.Element | null {
    const { experiment, exposures } = useValues(experimentLogic)
    const { reportExperimentExposureCoverageWarningShown } = useActions(eventUsageLogic)

    const coverage = exposures?.exposure_coverage

    useEffect(() => {
        if (coverage) {
            reportExperimentExposureCoverageWarningShown(experiment)
        }
    }, [reportExperimentExposureCoverageWarningShown, coverage, experiment])

    if (!coverage) {
        return null
    }

    const reasons = Object.keys(coverage.error_reasons).map((reason) => reason.replace(/_/g, ' '))

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="font-semibold">Some people never got a variant</div>
            <p className="m-0">
                <strong>{coverage.errored_percentage.toFixed(1)}%</strong> of the people who checked this flag only got
                an error back. They are missing from your exposures.
                {reasons.length > 0 && <> Reported errors: {reasons.join(', ')}.</>}
            </p>
            <p className="m-0 mt-1">
                The actual gap can be larger. An SDK that reads a flag before flags have loaded sends no event at all,
                so those people appear in neither count.{' '}
                <Link to="https://posthog.com/docs/feature-flags/bootstrapping" target="_blank">
                    Bootstrap your flags
                </Link>{' '}
                to give the SDK a value at startup.
            </p>
        </LemonBanner>
    )
}
