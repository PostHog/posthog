import './DashboardSubscribeExperiment.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconEllipsis } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

import { dashboardLogic } from './dashboardLogic'

type SubscribePlacement = 'button' | 'menu'

function SubscribeCountIcon({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { subscriptions } = useValues(subscriptionsLogic({ dashboardId }))

    return (
        <IconWithCount count={subscriptions?.length} showZero={false}>
            <IconBell className="DashboardSubscribeBell" fontSize="16" />
        </IconWithCount>
    )
}

function SubscribeIcon({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)

    // Only read the count when the subscriptions logic is already mounted (e.g. side panel opened),
    // so an experiment arm never triggers an extra fetch just to render this badge.
    if (!hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS) || !subscriptionsLogic.isMounted({ dashboardId })) {
        return <IconBell className="DashboardSubscribeBell" fontSize="16" />
    }

    return <SubscribeCountIcon dashboardId={dashboardId} />
}

// Both placements mount in the header; each renders only when it matches the assigned variant.
export function DashboardSubscribeExperiment({ placement }: { placement: SubscribePlacement }): JSX.Element | null {
    const { dashboard, canEditDashboard } = useValues(dashboardLogic)
    const { push } = useActions(router)
    const variant = useFeatureFlagVariantKey(FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_PLACEMENT)

    if (!dashboard || !canEditDashboard || variant !== placement) {
        return null
    }

    const dashboardId = dashboard.id
    const openSubscriptions = (): void => {
        posthog.capture('dashboard subscribe clicked', {
            dashboard_id: dashboardId,
            variant,
            surface: placement,
        })
        push(urlForSubscriptions({ dashboardId }))
    }

    if (placement === 'menu') {
        return (
            <LemonMenu
                items={[
                    {
                        label: 'Subscribe',
                        icon: <SubscribeIcon dashboardId={dashboardId} />,
                        onClick: openSubscriptions,
                        'data-attr': 'dashboard-subscribe-menu-item',
                    },
                ]}
            >
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconEllipsis fontSize="16" />}
                    data-attr="dashboard-subscribe-menu"
                    aria-label="More actions"
                />
            </LemonMenu>
        )
    }

    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<SubscribeIcon dashboardId={dashboardId} />}
            data-attr="dashboard-subscribe-prominent-button"
            onClick={openSubscriptions}
        >
            Subscribe
        </LemonButton>
    )
}
