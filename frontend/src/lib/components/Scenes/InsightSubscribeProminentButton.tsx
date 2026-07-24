import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightShortId } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

interface InsightSubscribeProminentButtonProps {
    insightShortId: InsightShortId
}

function SubscribeIcon({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId }))

    // Mirror the side-panel SceneSubscribeButton: show the active-subscription count badge so
    // the header button carries the same "you're already subscribed" signal.
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
 * Promotes "Subscribe" from the buried side-panel action to a visible header button.
 */
export function InsightSubscribeProminentButton({ insightShortId }: InsightSubscribeProminentButtonProps): JSX.Element {
    const { push } = useActions(router)

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
