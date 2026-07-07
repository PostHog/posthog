import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

import { AnyPropertyFilter, FeatureFlagEvaluationRuntime } from '~/types'

import { featureFlagConditionWarningLogic } from './featureFlagConditionWarningLogic'

export interface FeatureFlagConditionWarningProps {
    evaluationRuntime?: FeatureFlagEvaluationRuntime
    properties: AnyPropertyFilter[]
    className?: string
}

export function FeatureFlagConditionWarning({
    properties,
    className,
    evaluationRuntime = FeatureFlagEvaluationRuntime.ALL,
}: FeatureFlagConditionWarningProps): JSX.Element | null {
    const { warning } = useValues(featureFlagConditionWarningLogic({ properties, evaluationRuntime }))

    if (!warning) {
        return null
    }

    const mentionsStaticCohort = warning.includes('static cohorts')

    return (
        <div
            className={`flex items-start gap-2 text-xs p-2 rounded border border-primary bg-surface-secondary text-secondary${className ? ` ${className}` : ''}`}
        >
            <IconInfo className="text-base shrink-0 text-muted mt-0.5" />
            <span>
                This flag works as normal. Only <strong>local evaluation</strong> in server-side SDKs is affected by{' '}
                {warning}. These conditions are still evaluated through the PostHog API, just not from the SDK's local
                cache.
                {mentionsStaticCohort
                    ? ' If you need local evaluation, target a dynamic (behavioral) cohort instead of a static one.'
                    : ''}{' '}
                <Link to="https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation">
                    Learn more
                </Link>
            </span>
        </div>
    )
}
