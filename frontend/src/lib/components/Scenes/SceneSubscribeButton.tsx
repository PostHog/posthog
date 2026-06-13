import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightShortId, QueryBasedInsightModel } from '~/types'

import { subscriptionsLogic } from '../Subscriptions/subscriptionsLogic'
import { SubscriptionBaseProps, urlForSubscriptions } from '../Subscriptions/utils'
import { SceneDataAttrKeyProps } from './utils'

const SUBSCRIBE_LABEL_BY_VARIANT: Record<string, string> = {
    control: 'Subscribe',
    'recurring-updates': 'Get recurring updates',
    'scheduled-notifications': 'Schedule notifications',
    'scheduled-reports': 'Get scheduled reports',
}

interface SceneSubscribeButtonProps extends SubscriptionBaseProps, SceneDataAttrKeyProps {
    insight?: Partial<QueryBasedInsightModel>
    dashboardId?: number
}

function SubscribeIconWithCount({
    insightShortId,
    dashboardId,
}: {
    insightShortId?: InsightShortId
    dashboardId?: number
}): JSX.Element {
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId, dashboardId }))
    return (
        <IconWithCount count={subscriptions?.length} showZero={false}>
            <IconBell />
        </IconWithCount>
    )
}

export function SceneSubscribeButton({
    dataAttrKey,
    insight,
    dashboardId,
    disabledReasons,
}: SceneSubscribeButtonProps): JSX.Element {
    const { push } = useActions(router)
    const { hasAvailableFeature } = useValues(userLogic)
    const hasSubscriptionsFeature = hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS)
    const labelVariant = useFeatureFlagVariantKey(FEATURE_FLAGS.SCENE_SUBSCRIBE_LABEL_EXPERIMENT)
    const subscribeLabel =
        typeof labelVariant === 'string' ? (SUBSCRIBE_LABEL_BY_VARIANT[labelVariant] ?? 'Subscribe') : 'Subscribe'

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => {
                posthog.capture('scene subscribe menu item clicked', {
                    resource_type: dataAttrKey,
                    label_variant: typeof labelVariant === 'string' ? labelVariant : 'control',
                    label_text: subscribeLabel,
                })
                push(urlForSubscriptions({ insightShortId: insight?.short_id, dashboardId }))
            }}
            data-attr={`${dataAttrKey}-subscribe-dropdown-menu-item`}
            disabledReasons={disabledReasons}
        >
            {hasSubscriptionsFeature ? (
                <SubscribeIconWithCount insightShortId={insight?.short_id} dashboardId={dashboardId} />
            ) : (
                <IconBell />
            )}
            {subscribeLabel}
        </ButtonPrimitive>
    )
}
