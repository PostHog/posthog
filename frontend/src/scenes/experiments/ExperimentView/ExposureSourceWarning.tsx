import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { ExposureSourceRisk } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

/**
 * Surfaces exposures dominated by server-side flag evaluations. The backend only emits
 * `exposure_source_risk` for the default exposure event once the server-side share is above the
 * threshold, so presence of the field is the gate.
 */
export function ExposureSourceWarning(): JSX.Element | null {
    const { experiment, exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { reportExperimentExposureSourceWarningShown } = useActions(eventUsageLogic)

    const risk: ExposureSourceRisk | undefined = exposures?.exposure_source_risk

    useEffect(() => {
        if (risk) {
            reportExperimentExposureSourceWarningShown(experiment)
        }
    }, [reportExperimentExposureSourceWarningShown, risk, experiment])

    if (!risk) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div className="font-semibold">Exposures include server-side flag evaluations</div>
                    <p className="m-0">
                        <strong>{risk.server_side_percentage.toFixed(1)}%</strong> of exposed users were first seen
                        through {risk.libs.join(', ')}. On the default exposure event, evaluating the flag on your
                        backend counts a user as exposed even when no browser ever loaded. That includes bots,
                        prefetches, and requests that never rendered a page.
                    </p>
                    <p className="m-0 mt-1">
                        Those users can't trigger a front-end metric, so any drop-off between exposure and your first
                        metric will look larger than it is. To count only users who reached your app, pick a front-end
                        event as the exposure event, or add a property filter that keeps exposures with front-end
                        activity. Both live in{' '}
                        <Link to="https://posthog.com/docs/experiments/exposures" target="_blank">
                            exposure criteria
                        </Link>
                        .
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
