import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { DynamicCohortExposureRisk } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

/**
 * Surfaces exposure criteria that reference a dynamic cohort. Flag evaluation checks the
 * cohort's filters against live person properties, while the exposure query reads the
 * cohort's stored membership list, which only recalculates periodically — so exposure
 * counts can lag flag routing and drift into a sample ratio mismatch. The backend only
 * emits `dynamic_cohort_risk` when at least one referenced cohort is dynamic, so presence
 * of the field is the gate.
 */
export function DynamicCohortWarning(): JSX.Element | null {
    const { experiment, exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { reportExperimentDynamicCohortWarningShown } = useActions(eventUsageLogic)

    const risk: DynamicCohortExposureRisk | undefined = exposures?.dynamic_cohort_risk

    // Report once per experiment while the banner stays up. `experiment` is a fresh object on
    // every inline edit and `risk` is a fresh object on every exposures reload, so keying the
    // effect on either alone would re-report a banner that never went away.
    const reportedForExperimentId = useRef<Experiment['id'] | null>(null)

    useEffect(() => {
        if (!risk) {
            reportedForExperimentId.current = null
            return
        }
        if (reportedForExperimentId.current === experiment.id) {
            return
        }
        reportedForExperimentId.current = experiment.id
        reportExperimentDynamicCohortWarningShown(experiment)
    }, [reportExperimentDynamicCohortWarningShown, risk, experiment])

    if (!risk) {
        return null
    }

    const cohortLinks = risk.cohorts.map((cohort, index) => (
        <span key={cohort.id}>
            {index > 0 && ', '}
            <Link to={urls.cohort(cohort.id)} target="_blank">
                <strong>{cohort.name || `Cohort ${cohort.id}`}</strong>
            </Link>
        </span>
    ))

    // The remedy below points at the flag's release conditions, so name the flag where the action
    // is. feature_flag_key is always set; the linkable flag object is not, so fall back to text.
    const flagLabel = experiment.feature_flag ? (
        <Link to={urls.featureFlag(experiment.feature_flag.id)} target="_blank">
            <strong>{experiment.feature_flag_key}</strong>
        </Link>
    ) : (
        <strong>{experiment.feature_flag_key}</strong>
    )

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div className="font-semibold">
                        {risk.cohorts.length === 1
                            ? 'Exposure criteria uses a dynamic cohort'
                            : 'Exposure criteria uses dynamic cohorts'}
                    </div>
                    <p className="m-0">
                        This experiment filters exposures using the {risk.cohorts.length === 1 ? 'cohort' : 'cohorts'}{' '}
                        {cohortLinks}. The feature flag routes users by evaluating the cohort's filters against live
                        person properties, but the exposure query reads the cohort's stored membership list, which only
                        recalculates periodically. Users who qualify in the gap between recalculations are routed into a
                        variant before exposure counts reflect them.
                    </p>
                    <p className="m-0 mt-1">
                        This drift can grow into a sample ratio mismatch. Filter on the person properties directly
                        instead — ideally in both {flagLabel}'s release conditions and the{' '}
                        <Link to="https://posthog.com/docs/experiments/exposures" target="_blank">
                            exposure criteria
                        </Link>{' '}
                        — so flag routing and the exposure query stay in sync.
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
