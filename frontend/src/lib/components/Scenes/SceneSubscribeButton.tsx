import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SubscriptionBaseProps, urlForSubscriptions } from '../Subscriptions/utils'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { SceneDataAttrKeyProps } from './utils'
import { QueryBasedInsightModel } from '~/types'
import { IconBell } from '@posthog/icons'

interface SceneSubscribeButtonProps extends SubscriptionBaseProps, SceneDataAttrKeyProps {
    insight?: Partial<QueryBasedInsightModel>
    dashboardId?: number
}

export function SceneSubscribeButton({ dataAttrKey, insight, dashboardId }: SceneSubscribeButtonProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => push(urlForSubscriptions({ insightShortId: insight?.short_id, dashboardId }))}
            data-attr={`${dataAttrKey}-subscribe-dropdown-menu-item`}
        >
            <IconBell />
            Subscribe
        </ButtonPrimitive>
    )
}
