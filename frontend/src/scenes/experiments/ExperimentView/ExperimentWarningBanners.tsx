import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { getEventPropertiesForExperiment } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import type { Experiment } from '~/types'

import { healthFindingForExperimentWarning } from 'products/experiments/frontend/health/experimentHealthFindingEvents'
import { useHealthFindingReporting } from 'products/experiments/frontend/health/useHealthFindingReporting'

import { experimentLogic } from '../experimentLogic'
import type { ExperimentWarning } from '../experimentLogic'

function reportExperimentInconsistencyWarningShown(experiment: Experiment, warningKey: string): void {
    posthog.capture('experiment inconsistency warning shown', {
        ...getEventPropertiesForExperiment(experiment),
        warning_key: warningKey,
    })
}

function warningCaption(key: ExperimentWarning['key']): string {
    switch (key) {
        case 'running_but_flag_disabled':
            return 'The experiment is paused'
        case 'running_but_single_variant_shipped':
            return 'The experiment is running, but all users see a single variant'
        case 'running_but_no_rollout':
            return 'The experiment is running, but no new users are being exposed'
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
                    {warning.variantKey ? (
                        <>
                            Variant <strong>"{warning.variantKey}"</strong> is
                        </>
                    ) : (
                        'One variant is'
                    )}{' '}
                    rolled out to 100% of users. The experiment is not comparing variants. End the experiment with a
                    conclusion, or adjust the variant distribution in {flagLink} to resume proper A/B testing.
                </>
            )
        case 'running_but_no_rollout':
            return (
                <>
                    The feature flag {flagLink} has a <strong>0% rollout</strong>, so no new users are being exposed.
                    Users exposed earlier are still included in the results. End the experiment with a conclusion, or
                    increase the rollout percentage to expose users.
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
    const { reportActedOn } = useHealthFindingReporting(
        experimentWarning ? healthFindingForExperimentWarning(experimentWarning.key) : null
    )

    useEffect(() => {
        if (experimentWarning) {
            reportExperimentInconsistencyWarningShown(experiment, experimentWarning.key)
        }
    }, [experimentWarning, experiment])

    if (!experimentWarning) {
        return null
    }

    const flagLink = experiment.feature_flag ? (
        <Link
            target="_blank"
            to={urls.featureFlag(experiment.feature_flag.id)}
            onClick={() => reportActedOn('open_feature_flag')}
        >
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
