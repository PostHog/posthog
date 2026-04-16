import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { QueryBasedInsightModel } from '~/types'

import { subscriptionsLogic } from '../Subscriptions/subscriptionsLogic'
import { SubscriptionBaseProps, urlForSubscriptions } from '../Subscriptions/utils'
import { SceneDataAttrKeyProps } from './utils'

interface SceneSubscribeButtonProps extends SubscriptionBaseProps, SceneDataAttrKeyProps {
    insight?: Partial<QueryBasedInsightModel>
    dashboardId?: number
}

export function SceneSubscribeButton({
    dataAttrKey,
    insight,
    dashboardId,
    disabledReasons,
}: SceneSubscribeButtonProps): JSX.Element {
    const { push } = useActions(router)
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId: insight?.short_id, dashboardId }))

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => push(urlForSubscriptions({ insightShortId: insight?.short_id, dashboardId }))}
            data-attr={`${dataAttrKey}-subscribe-dropdown-menu-item`}
            disabledReasons={disabledReasons}
        >
            <IconWithCount count={subscriptions?.length} showZero={false}>
                <IconBell />
            </IconWithCount>
            Subscribe
        </ButtonPrimitive>
    )
}
