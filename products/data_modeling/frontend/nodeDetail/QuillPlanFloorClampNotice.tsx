import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { planFloorClampMessage } from 'scenes/data-warehouse/saved_queries/PlanFloorClampBanner'
import { urls } from 'scenes/urls'

export interface QuillPlanFloorClampNoticeProps {
    subject: 'view' | 'endpoint'
    savedQueryId: string
    previousSeconds: number | null
    planFloorSeconds: number
    at: string
}

export function QuillPlanFloorClampNotice({
    subject,
    savedQueryId,
    previousSeconds,
    planFloorSeconds,
    at,
}: QuillPlanFloorClampNoticeProps): JSX.Element | null {
    const logic = lemonBannerLogic({ dismissKey: `plan-floor-clamp-${savedQueryId}-${at}` })
    const { isDismissed } = useValues(logic)
    const { dismiss } = useActions(logic)

    if (isDismissed) {
        return null
    }

    return (
        <Item variant="outline" size="sm" tone="info" className="flex-wrap">
            <ItemContent className="min-w-0">
                <ItemDescription>{planFloorClampMessage(subject, previousSeconds, planFloorSeconds)}</ItemDescription>
            </ItemContent>
            <ItemActions className="flex-wrap">
                <Button
                    variant="outline"
                    size="sm"
                    render={<LinkPrimitive to={urls.organizationBilling()} />}
                    data-attr="plan-floor-clamp-upgrade"
                >
                    Upgrade plan
                </Button>
                <Button size="icon-sm" onClick={dismiss} aria-label="Dismiss" tooltip="Dismiss">
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
