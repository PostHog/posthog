import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { confirmResetExperiment } from '../experimentActions'
import { experimentLogic } from '../experimentLogic'
import type { ExperimentWarning } from '../experimentLogic'

function warningCaption(key: ExperimentWarning['key']): string {
    switch (key) {
        case 'running_but_flag_disabled':
            return 'The experiment is paused'
        case 'running_but_single_variant_shipped':
        case 'running_but_no_rollout':
            return 'The experiment is running, but no users are exposed to the A/B test'
        case 'ended_but_multiple_variants_rolled_out':
        case 'not_started_but_multiple_variants_rolled_out':
            return 'The experiment is not running, but users are exposed to multiple variants'
        case 'distribution_changed_while_running':
            return 'The variant split changed while the experiment was running'
    }
}

function WarningDetail({
    warning,
    flagLink,
}: {
    warning: ExperimentWarning
    flagLink: JSX.Element | null
}): JSX.Element {
    switch (warning.key) {
        case 'running_but_flag_disabled':
            return (
                <>
                    The linked feature flag {flagLink} is <strong>disabled</strong> while the experiment has not been
                    ended. Resume or end the experiment.
                </>
            )
        case 'running_but_single_variant_shipped':
            return (
                <>
                    Variant <strong>"{warning.variantKey}"</strong> is rolled out to 100% of users. The experiment is
                    not comparing variants. End the experiment with a conclusion, or adjust the variant distribution in{' '}
                    {flagLink} to resume proper A/B testing.
                </>
            )
        case 'running_but_no_rollout':
            return (
                <>
                    The feature flag {flagLink} has a <strong>0% rollout</strong>. End the experiment with a conclusion,
                    or increase the rollout percentage to start collecting data.
                </>
            )
        case 'ended_but_multiple_variants_rolled_out':
            return (
                <>
                    This experiment has ended, but the feature flag {flagLink} is still <strong>active</strong> and
                    distributing traffic across multiple variants. Disable the flag, or resume the experiment.
                </>
            )
        case 'not_started_but_multiple_variants_rolled_out':
            return (
                <>
                    This experiment hasn't launched yet, but the feature flag {flagLink} is already{' '}
                    <strong>active</strong> and exposing users to multiple variants. Disable the flag, or start the
                    experiment.
                </>
            )
        case 'distribution_changed_while_running':
            return (
                <>
                    The split between the variants of {flagLink} changed
                    {warning.changedAt ? (
                        <>
                            {' '}
                            <TZLabel time={warning.changedAt} />
                        </>
                    ) : null}
                    , so these results mix data from before and after the change. Users are assigned by a stable hash of
                    their ID, so only the users in the part of the range you moved switched variants. Everyone else kept
                    the variant they already had.{' '}
                    <Link to="https://posthog.com/docs/experiments/changing-distribution-after-rollout" target="_blank">
                        Read more
                    </Link>
                </>
            )
    }
}

/** Ways out of a mid-run split change: drop the results collected under the old split, or start over. */
function DistributionChangedActions({ changedAt }: { changedAt: string }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, resetRunningExperiment } = useActions(experimentLogic)

    return (
        <div className="flex gap-2 items-center flex-shrink-0">
            <LemonButton size="small" type="secondary" onClick={() => changeExperimentStartDate(changedAt)}>
                Move start date to the change
            </LemonButton>
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => confirmResetExperiment(experiment, resetRunningExperiment)}
            >
                Reset analysis
            </LemonButton>
        </div>
    )
}

export function ExperimentWarningBanner(): JSX.Element | null {
    const { experimentWarning, experiment } = useValues(experimentLogic)
    const { reportExperimentInconsistencyWarningShown } = useActions(eventUsageLogic)

    useEffect(() => {
        if (experimentWarning) {
            reportExperimentInconsistencyWarningShown(experiment, experimentWarning.key)
        }
    }, [reportExperimentInconsistencyWarningShown, experimentWarning, experiment])

    if (!experimentWarning) {
        return null
    }

    const flagLink = experiment.feature_flag ? (
        <Link target="_blank" to={urls.featureFlag(experiment.feature_flag.id)}>
            {experiment.feature_flag.key}
        </Link>
    ) : null

    const changedAt =
        experimentWarning.key === 'distribution_changed_while_running' ? experimentWarning.changedAt : null

    return (
        <LemonBanner className="mb-4" type="warning">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div>
                        <strong>{warningCaption(experimentWarning.key)}</strong>
                    </div>
                    <div>
                        <WarningDetail warning={experimentWarning} flagLink={flagLink} />
                    </div>
                </div>
                {changedAt && <DistributionChangedActions changedAt={changedAt} />}
            </div>
        </LemonBanner>
    )
}
