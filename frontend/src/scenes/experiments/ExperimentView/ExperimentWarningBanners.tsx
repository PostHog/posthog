import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

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
                    not comparing variants. End the experiment with a conclusion, or adjust the variant distribution in
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
    }
}

export function ExperimentWarningBanner(): JSX.Element | null {
    const { experimentWarning, experiment } = useValues(experimentLogic)
    const { reportExperimentInconsistencyWarningShown } = useActions(eventUsageLogic)

    useEffect(() => {
        if (experimentWarning) {
            reportExperimentInconsistencyWarningShown(experiment, experimentWarning.key)
        }
    }, [experimentWarning?.key])

    if (!experimentWarning) {
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
                <strong>{warningCaption(experimentWarning.key)}</strong>
            </div>
            <div>
                <WarningDetail warning={experimentWarning} flagLink={flagLink} />
            </div>
        </LemonBanner>
    )
}
