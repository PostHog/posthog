import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightShortId } from '~/types'

import { subscriptionsLogic } from '../Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from '../Subscriptions/utils'

interface InsightSubscribeProminentButtonProps {
    insightShortId: InsightShortId
}

function SubscribeIcon({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId }))

    // Mirror the side-panel SceneSubscribeButton: show the active-subscription count badge so
    // the test arm carries the same "you're already subscribed" signal as the control arm.
    if (!hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS)) {
        return <IconBell />
    }

    return (
        <IconWithCount count={subscriptions?.length} showZero={false}>
            <IconBell />
        </IconWithCount>
    )
}

/**
 * Experiment (insight-subscribe-prominent-button): promotes "Subscribe" from the buried
 * side-panel action to a visible header button. Reading the flag variant here is the
 * experiment exposure, so this is mounted only for subscribe-eligible insights to keep the
 * exposed population aligned with the control arm.
 */
export function InsightSubscribeProminentButton({
    insightShortId,
}: InsightSubscribeProminentButtonProps): JSX.Element | null {
    const { push } = useActions(router)
    const variant = useFeatureFlagVariantKey(FEATURE_FLAGS.INSIGHT_SUBSCRIBE_PROMINENT_BUTTON)

    if (variant !== 'test') {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<SubscribeIcon insightShortId={insightShortId} />}
            data-attr="insight-subscribe-prominent-button"
            onClick={() => {
                posthog.capture('insight subscribe prominent button clicked', {
                    insight_short_id: insightShortId,
                })
                push(urlForSubscriptions({ insightShortId }))
            }}
        >
            Subscribe
        </LemonButton>
    )
}
