import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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

    return (
        <LemonBanner type="warning" className={className}>
            This flag cannot be locally evaluated by server-side SDKs due to unsupported features: {warning}. The flag
            will still evaluate correctly when not using local evaluation.{' '}
            <Link to="https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation">
                Learn more
            </Link>
        </LemonBanner>
    )
}
