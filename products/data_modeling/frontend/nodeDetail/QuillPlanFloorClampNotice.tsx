import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { planFloorClampMessage } from 'scenes/data-warehouse/saved_queries/PlanFloorClampBanner'
import { urls } from 'scenes/urls'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function QuillPlanFloorClampNotice({ id }: { id: string }): JSX.Element | null {
    const { node, savedQuery: initialSavedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const subject = node?.type === 'endpoint' ? 'endpoint' : 'view'
    const { savedQuery: currentSavedQuery } = useValues(
        materializationJobsLogic({ viewId: node?.saved_query_id ?? '', kind: subject })
    )
    const clamp = (currentSavedQuery ?? initialSavedQuery)?.plan_clamp
    const logic = lemonBannerLogic({ dismissKey: `plan-floor-clamp-${node?.saved_query_id}-${clamp?.at}` })
    const { isDismissed } = useValues(logic)
    const { dismiss } = useActions(logic)

    if (!clamp || isDismissed) {
        return null
    }

    return (
        <Item variant="outline" size="sm" tone="info" className="flex-wrap">
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">
                    {planFloorClampMessage(subject, clamp.previous_target_seconds, clamp.plan_floor_seconds)}
                </ItemDescription>
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
