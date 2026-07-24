import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconBell, IconWarning } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightShortId } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { urlForSubscriptions } from 'products/subscriptions/frontend/components/Subscriptions/utils'

interface InsightSubscribeProminentButtonProps {
    insightShortId: InsightShortId
    canCreateAlert: boolean
}

function notificationLabelForVariant(variant: boolean | string | undefined): string | null {
    switch (variant) {
        case 'notifications':
            return 'Notifications'
        case 'get-updates':
            return 'Get updates'
        case 'monitor':
            return 'Monitor'
        default:
            return null
    }
}

function SubscribeIcon({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { subscriptions } = useValues(subscriptionsLogic({ insightShortId }))

    // Mirror the side-panel SceneSubscribeButton: show the active-subscription count badge so
    // the header button carries the same "you're already subscribed" signal.
    if (!hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS)) {
        return <IconBell />
    }

    return (
        <IconWithCount count={subscriptions?.length} showZero={false}>
            <IconBell />
        </IconWithCount>
    )
}

export function InsightSubscribeProminentButton({
    insightShortId,
    canCreateAlert,
}: InsightSubscribeProminentButtonProps): JSX.Element {
    if (!canCreateAlert) {
        return <SubscribeButton insightShortId={insightShortId} />
    }

    return <ExperimentButton insightShortId={insightShortId} />
}

function ExperimentButton({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { push } = useActions(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const notificationEntrypointVariant = featureFlags[FEATURE_FLAGS.INSIGHT_NOTIFICATION_ENTRYPOINT]
    const notificationLabel = notificationLabelForVariant(notificationEntrypointVariant)

    if (notificationLabel) {
        return (
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconBell />}
                        data-attr="insight-notify-prominent-button"
                    >
                        {notificationLabel}
                    </LemonButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuGroup>
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    posthog.capture('insight notify prominent button clicked', {
                                        insight_short_id: insightShortId,
                                        option: 'alerts',
                                        header_copy: notificationLabel,
                                    })
                                    push(urls.insightAlerts(insightShortId))
                                }}
                            >
                                <IconWarning />
                                <span className="flex flex-col">
                                    <span>Alerts</span>
                                    <span className="text-secondary text-xs">
                                        Notify me when the insight meets a condition
                                    </span>
                                </span>
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    posthog.capture('insight notify prominent button clicked', {
                                        insight_short_id: insightShortId,
                                        option: 'subscriptions',
                                        header_copy: notificationLabel,
                                    })
                                    push(urlForSubscriptions({ insightShortId }))
                                }}
                            >
                                <IconBell />
                                <span className="flex flex-col">
                                    <span>Subscriptions</span>
                                    <span className="text-secondary text-xs">Send me a recurring report</span>
                                </span>
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    }

    return <SubscribeButton insightShortId={insightShortId} />
}

function SubscribeButton({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element {
    const { push } = useActions(router)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<SubscribeIcon insightShortId={insightShortId} />}
            data-attr="insight-subscribe-prominent-button"
            onClick={() => {
                posthog.capture('insight subscribe prominent button clicked', {
                    insight_short_id: insightShortId,
                })
                push(urlForSubscriptions({ insightShortId }))
            }}
        >
            Subscribe
        </LemonButton>
    )
}
