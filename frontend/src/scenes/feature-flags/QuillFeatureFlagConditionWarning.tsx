import { useValues } from 'kea'

import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { FeatureFlagEvaluationRuntime } from '~/types'

import { FeatureFlagConditionWarningProps } from './FeatureFlagConditionWarning'
import { featureFlagConditionWarningLogic } from './featureFlagConditionWarningLogic'

export function QuillFeatureFlagConditionWarning({
    properties,
    evaluationRuntime = FeatureFlagEvaluationRuntime.ALL,
}: Omit<FeatureFlagConditionWarningProps, 'className'>): JSX.Element | null {
    const { warning, hasStaticCohort } = useValues(featureFlagConditionWarningLogic({ properties, evaluationRuntime }))

    if (!warning) {
        return null
    }

    return (
        <Item tone="info" size="sm">
            <ItemContent>
                <ItemDescription>
                    This flag works as normal. Only <strong>local evaluation</strong> in server-side SDKs is affected by
                    these conditions: {warning}. They are still evaluated through the PostHog API, just not from the
                    SDK's local cache.
                    {hasStaticCohort
                        ? ' If you need local evaluation, target a dynamic (behavioral) cohort instead of a static one.'
                        : ''}{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive to="https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation" />
                        }
                    >
                        Learn more
                    </Button>
                </ItemDescription>
            </ItemContent>
        </Item>
    )
}
