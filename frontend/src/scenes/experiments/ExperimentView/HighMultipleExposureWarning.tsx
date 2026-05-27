import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

// Threshold above which a high `$multiple` exposure share is surfaced as a
// contamination warning. Below this, the share is generally not large enough
// to materially distort metric estimates.
const HIGH_MULTIPLE_EXPOSURE_THRESHOLD_PERCENT = 10

/**
 * Surfaces a high share of users exposed to multiple variants. Above the
 * threshold, results can be contaminated regardless of how `$multiple` is
 * handled. Complementary to `MultiVariantBiasWarning`, which targets the
 * uneven-split + EXCLUDE asymmetric-exclusion case; suppressed when that
 * warning already fires to avoid stacking two banners about the same data.
 */
export function HighMultipleExposureWarning(): JSX.Element | null {
    const { experiment, exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { reportExperimentHighMultipleExposureWarningShown } = useActions(eventUsageLogic)

    let multiplePercentage = 0
    if (exposures?.total_exposures) {
        let total = 0
        for (const value of Object.values(exposures.total_exposures)) {
            total += Number(value)
        }
        const multipleCount = Number(exposures.total_exposures[EXPERIMENT_VARIANT_MULTIPLE] || 0)
        multiplePercentage = total > 0 ? (multipleCount / total) * 100 : 0
    }

    const shouldShow = multiplePercentage > HIGH_MULTIPLE_EXPOSURE_THRESHOLD_PERCENT && !exposures?.bias_risk

    useEffect(() => {
        if (shouldShow) {
            reportExperimentHighMultipleExposureWarningShown(experiment, multiplePercentage)
        }
    }, [reportExperimentHighMultipleExposureWarningShown, shouldShow, experiment, multiplePercentage])

    if (!shouldShow) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div className="font-semibold">High multiple-variant exposure rate</div>
                    <p className="m-0">
                        <strong>{multiplePercentage.toFixed(1)}%</strong> of users were exposed to more than one variant
                        (above the {HIGH_MULTIPLE_EXPOSURE_THRESHOLD_PERCENT}% threshold). These users contribute
                        behavior from multiple variants, which can contaminate your results and make it harder to
                        measure each variant's true impact.
                    </p>
                    <p className="m-0 mt-1">
                        Common causes include feature flag changes mid-experiment, users switching devices or browsers
                        before identification, or short cookie lifetimes. See{' '}
                        <Link
                            to="https://posthog.com/docs/experiments/exposures#handling-multiple-exposures"
                            target="_blank"
                        >
                            handling multiple exposures
                        </Link>{' '}
                        for guidance.
                    </p>
                </div>
                <div className="flex gap-2 items-center flex-shrink-0">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => openExposureCriteriaModal(exposureCriteria)}
                    >
                        Edit exposure criteria
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
