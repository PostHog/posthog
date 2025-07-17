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

interface SceneNotificationDropdownMenuProps extends SubscriptionBaseProps {
    insight?: Partial<QueryBasedInsightModel>
    insightLogicProps?: InsightLogicProps
    dashboardId?: number
    buttonProps?: Omit<ButtonPrimitiveProps, 'children'>
}

interface AlertsDropdownMenuItemProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

function AlertsDropdownMenuItem({
    insightId,
    insightShortId,
    insightLogicProps,
}: AlertsDropdownMenuItemProps): JSX.Element {
    const { push } = useActions(router)

    const logic = insightAlertsLogic({ insightId, insightLogicProps })
    const { alerts } = useValues(logic)

    return (
        <DropdownMenuItem className="w-full">
            <ButtonPrimitive menuItem onClick={() => push(urls.insightAlerts(insightShortId))}>
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
}: SceneNotificationDropdownMenuProps): JSX.Element | null {
    const { push } = useActions(router)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem {...buttonProps}>
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
                    />
                )}
                <DropdownMenuItem className="w-full">
                    <ButtonPrimitive
                        menuItem
                        onClick={() => push(urlForSubscriptions({ insightShortId: insight?.short_id, dashboardId }))}
                    >
                        <IconBell />
                        Subscribe
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
