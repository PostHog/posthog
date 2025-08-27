import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconBell } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { QueryBasedInsightModel } from '~/types'

import { SubscriptionBaseProps, urlForSubscriptions } from '../Subscriptions/utils'
import { SceneDataAttrKeyProps } from './utils'

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
