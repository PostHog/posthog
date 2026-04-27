import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

import { AnyPropertyFilter, FeatureFlagEvaluationRuntime, FeatureFlagGroupType } from '~/types'

import { featureFlagConditionWarningLogic } from './featureFlagConditionWarningLogic'

export interface FeatureFlagConditionWarningProps {
    evaluationRuntime?: FeatureFlagEvaluationRuntime
    properties: AnyPropertyFilter[]
    filterGroups?: FeatureFlagGroupType[]
    className?: string
}

export function FeatureFlagConditionWarning({
    properties,
    filterGroups,
    className,
    evaluationRuntime = FeatureFlagEvaluationRuntime.ALL,
}: FeatureFlagConditionWarningProps): JSX.Element | null {
    const { warning } = useValues(featureFlagConditionWarningLogic({ properties, evaluationRuntime, filterGroups }))

    if (!warning) {
        return null
    }

    return (
        <div
            className={`flex items-center gap-2 text-xs p-2 rounded border border-warning-dark bg-warning-highlight${className ? ` ${className}` : ''}`}
        >
            <IconInfo className="text-base shrink-0 text-warning-dark" />
            <span>
                Local evaluation unavailable ({warning}).{' '}
                <Link to="https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation">
                    Learn more
                </Link>
            </span>
        </div>
    )
}
