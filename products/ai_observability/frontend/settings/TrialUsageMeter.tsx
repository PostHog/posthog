import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { EvaluationTrialConfig, llmProviderKeysLogic } from './llmProviderKeysLogic'

function TrialDeprecationBanner({
    deprecationDate,
    showSettingsLink,
    noun,
}: {
    deprecationDate: string
    showSettingsLink: boolean
    noun: string
}): JSX.Element {
    const endDate = dayjs.utc(deprecationDate).format('MMMM D, YYYY')

    return (
        <LemonBanner type="warning">
            Trial {noun} are being phased out and will be removed on {endDate}.{' '}
            {showSettingsLink ? (
                <Link to={urls.settings('project-ai-observability', 'ai-observability-byok')}>Add a provider key</Link>
            ) : (
                'Add a provider key'
            )}{' '}
            to keep {noun} working without interruption.
        </LemonBanner>
    )
}

export function TrialUsageMeter({
    showSettingsLink = false,
    noun = 'evaluations',
}: {
    showSettingsLink?: boolean
    noun?: string
}): JSX.Element | null {
    const { evaluationConfig } = useValues(llmProviderKeysLogic)

    // Terminal teams get no trial UI at all — post-deprecation the trial should look like it never existed.
    if (!evaluationConfig || !evaluationConfig.trial_grandfathered || evaluationConfig.active_provider_key) {
        return null
    }

    return (
        <div className="space-y-3">
            <TrialDeprecationBanner
                deprecationDate={evaluationConfig.trial_deprecation_date}
                showSettingsLink={showSettingsLink}
                noun={noun}
            />
            <TrialUsageMeterDisplay
                evaluationConfig={evaluationConfig}
                showSettingsLink={showSettingsLink}
                noun={noun}
            />
        </div>
    )
}

function TrialUsageMeterDisplay({
    evaluationConfig,
    showSettingsLink = false,
    noun = 'evaluations',
}: {
    evaluationConfig: EvaluationTrialConfig
    showSettingsLink?: boolean
    noun?: string
}): JSX.Element {
    const { trial_eval_limit, trial_evals_remaining } = evaluationConfig
    const percentUsed = Math.min(((trial_eval_limit - trial_evals_remaining) / trial_eval_limit) * 100, 100)

    return (
        <div className="rounded-lg p-4 space-y-3 border">
            <div className="flex justify-between items-center">
                <span className="font-medium">Trial {noun}</span>
                <span className="text-sm text-muted">
                    {trial_evals_remaining} of {trial_eval_limit} remaining
                </span>
            </div>
            <div className="h-2 bg-border rounded-full overflow-hidden">
                <div
                    className="h-full transition-all bg-success"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${percentUsed}%` }}
                />
            </div>
            <p className="text-sm text-muted">
                You have {trial_evals_remaining} {noun} to try things out before{' '}
                {showSettingsLink ? (
                    <Link to={urls.settings('project-ai-observability', 'ai-observability-byok')}>
                        adding your own key
                    </Link>
                ) : (
                    'adding your own key'
                )}
                .
            </p>
        </div>
    )
}
