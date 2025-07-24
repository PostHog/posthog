import { IconBell, IconNotification, IconWarning } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'
import { InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'
import { insightAlertsLogic } from '../../Alerts/insightAlertsLogic'
import { SubscriptionBaseProps, urlForSubscriptions } from '../../Subscriptions/utils'
import { SceneDataAttrKeyProps } from '../utils'

interface SceneNotificationDropdownMenuProps extends SubscriptionBaseProps, SceneDataAttrKeyProps {
    insight?: Partial<QueryBasedInsightModel>
    insightLogicProps?: InsightLogicProps
    dashboardId?: number
    buttonProps?: Omit<ButtonPrimitiveProps, 'children'>
}

interface AlertsDropdownMenuItemProps extends SceneDataAttrKeyProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

function AlertsDropdownMenuItem({
    insightId,
    insightShortId,
    insightLogicProps,
    dataAttrKey,
}: AlertsDropdownMenuItemProps): JSX.Element {
    const { push } = useActions(router)

    const logic = insightAlertsLogic({ insightId, insightLogicProps })
    const { alerts } = useValues(logic)

    return (
        <DropdownMenuItem className="w-full">
            <ButtonPrimitive
                menuItem
                onClick={() => push(urls.insightAlerts(insightShortId))}
                data-attr={`${dataAttrKey}-alerts-dropdown-menu-item`}
            >
                <IconWithCount count={alerts?.length} showZero={false}>
                    <IconWarning />
                </IconWithCount>
                Alerts
            </ButtonPrimitive>
        </DropdownMenuItem>
    )
}

export function SceneNotificationDropdownMenu({
    buttonProps,
    insight,
    insightLogicProps,
    dashboardId,
    dataAttrKey,
}: SceneNotificationDropdownMenuProps): JSX.Element | null {
    const { push } = useActions(router)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem {...buttonProps} data-attr={`${dataAttrKey}-notifications-dropdown-menu`}>
                    <IconNotification />
                    Notifications
                    <DropdownMenuOpenIndicator className="ml-auto" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" matchTriggerWidth>
                {insight && insight.id && insight.short_id && insightLogicProps && (
                    <AlertsDropdownMenuItem
                        insightId={insight.id}
                        insightShortId={insight.short_id}
                        insightLogicProps={insightLogicProps}
                        dataAttrKey={dataAttrKey}
                    />
                )}
                <DropdownMenuItem className="w-full">
                    <ButtonPrimitive
                        menuItem
                        onClick={() => push(urlForSubscriptions({ insightShortId: insight?.short_id, dashboardId }))}
                        data-attr={`${dataAttrKey}-subscribe-dropdown-menu-item`}
                    >
                        <IconBell />
                        Subscribe
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
