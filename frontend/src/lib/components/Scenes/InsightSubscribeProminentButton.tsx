import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { InsightShortId } from '~/types'

import { urlForSubscriptions } from '../Subscriptions/utils'

interface InsightSubscribeProminentButtonProps {
    insightShortId: InsightShortId
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
            icon={<IconBell />}
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
