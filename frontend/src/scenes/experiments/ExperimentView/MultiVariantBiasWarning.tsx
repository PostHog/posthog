import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

/**
 * Surfaces empirically observed multi-variant exclusion bias: uneven split + `EXCLUDE`
 * handling + observed `$multiple` share above the threshold. The backend only emits
 * `bias_risk` when all three conditions hold, so presence of the field is the gate.
 */
export function MultiVariantBiasWarning(): JSX.Element | null {
    const { experiment, exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const { openDistributionModal } = useActions(modalsLogic)
    const { reportExperimentBiasWarningShown } = useActions(eventUsageLogic)

    const risk = exposures?.bias_risk

    useEffect(() => {
        if (risk) {
            reportExperimentBiasWarningShown(experiment)
        }
    }, [reportExperimentBiasWarningShown, risk, experiment])

    if (!risk) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div>
                        <strong>Setup likely introduced bias</strong>
                    </div>
                    <div>
                        <strong>{risk.multiple_variant_percentage.toFixed(1)}%</strong> of users were exposed to
                        multiple variants. With your uneven variant split and the current <strong>Exclude</strong>{' '}
                        handling, users were disproportionately dropped from the smaller variant. If their behavior
                        differs from other users, the smaller variant's metrics will be biased.
                    </div>
                    <div className="mt-1">
                        We recommend using an <strong>even split</strong> and controlling exposure with the overall
                        rollout (uneven splits have further disadvantages). Alternatively use{' '}
                        <Link
                            to="https://posthog.com/docs/experiments/exposures#handling-multiple-exposures"
                            target="_blank"
                        >
                            <strong>First seen</strong>
                        </Link>{' '}
                        handling.
                    </div>
                </div>
                <div className="flex gap-2 items-center flex-shrink-0">
                    <LemonButton type="secondary" onClick={() => openDistributionModal()}>
                        Adjust distribution
                    </LemonButton>
                    <LemonButton type="secondary" onClick={() => openExposureCriteriaModal(exposureCriteria)}>
                        Use first seen variant
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
