import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { MultiVariantBiasKind } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

const FIRST_SEEN_DOCS = 'https://posthog.com/docs/experiments/exposures#handling-multiple-exposures'

/**
 * Surfaces multi-variant exclusion bias under `EXCLUDE` handling: the observed `$multiple`
 * share is above the threshold, so users assigned to more than one variant are dropped from
 * every metric. The backend only emits `bias_risk` when that holds, so presence of the field
 * is the gate. `kind` picks the copy: an uneven split drops the smaller variant harder,
 * while an even split still drops a non-random population when distinct IDs churn.
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

    const share = <strong>{risk.multiple_variant_percentage.toFixed(1)}%</strong>
    const isAsymmetric = risk.kind === MultiVariantBiasKind.AsymmetricExclusion

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    {isAsymmetric ? (
                        <>
                            <div className="font-semibold">Setup likely introduced bias</div>
                            <p className="m-0">
                                {share} of users were exposed to multiple variants. With your uneven variant split and
                                the current <strong>Exclude</strong> handling, users were disproportionately dropped
                                from the smaller variant. If their behavior differs from other users, the smaller
                                variant's metrics will be biased.
                            </p>
                            <p className="m-0 mt-1">
                                We recommend using an <strong>even split</strong> and controlling exposure with the
                                overall rollout (uneven splits have further disadvantages). Alternatively use{' '}
                                <Link to={FIRST_SEEN_DOCS} target="_blank">
                                    <strong>First seen</strong>
                                </Link>{' '}
                                handling.
                            </p>
                        </>
                    ) : (
                        <>
                            <div className="font-semibold">Some users are dropped from results</div>
                            <p className="m-0">
                                {share} of users were exposed to multiple variants, and the current{' '}
                                <strong>Exclude</strong> handling drops them from every metric. This often happens when
                                one person gets different distinct IDs, for example before and after logging in, so they
                                are hashed into different variants. Users who log in mid-session are dropped more than
                                others, which can bias your results.
                            </p>
                            <p className="m-0 mt-1">
                                We recommend{' '}
                                <Link to={FIRST_SEEN_DOCS} target="_blank">
                                    <strong>First seen</strong>
                                </Link>{' '}
                                handling, which keeps these users on the first variant they saw.
                            </p>
                        </>
                    )}
                </div>
                <div className="flex gap-2 items-center flex-shrink-0">
                    {isAsymmetric && (
                        <LemonButton size="small" type="secondary" onClick={() => openDistributionModal()}>
                            Adjust distribution
                        </LemonButton>
                    )}
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() =>
                            openExposureCriteriaModal({
                                ...exposureCriteria,
                                multiple_variant_handling: 'first_seen',
                            })
                        }
                    >
                        Use first seen variant
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
