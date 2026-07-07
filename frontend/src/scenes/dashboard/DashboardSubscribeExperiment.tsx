import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconMenu } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { subscriptionsLogic } from 'lib/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'lib/components/Subscriptions/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { dashboardLogic } from './dashboardLogic'

type SubscribePlacement = 'button' | 'menu'

function SubscribeIcon({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { subscriptions } = useValues(subscriptionsLogic({ dashboardId }))

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
 * A/B tests surfacing dashboard subscriptions outside the side panel. `button` renders an explicit
 * header button; `menu` renders a hamburger menu to the right of Add. Only the slot matching the
 * assigned flag variant renders — the other returns null so both placements can live in the header.
 */
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
                    type="secondary"
                    size="small"
                    icon={<IconMenu fontSize="16" />}
                    data-attr="dashboard-subscribe-menu"
                    aria-label="More actions"
                />
            </LemonMenu>
        )
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<SubscribeIcon dashboardId={dashboardId} />}
            data-attr="dashboard-subscribe-prominent-button"
            onClick={openSubscriptions}
        >
            Subscribe
        </LemonButton>
    )
}
