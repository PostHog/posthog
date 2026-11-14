import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import {
    eventsRetentionDeletionWarningLogic,
    eventsRetentionSettingsUrl,
} from '~/layout/eventsRetentionDeletionWarningLogic'

export function EventsRetentionDeletionWarning({ isCollapsed }: { isCollapsed: boolean }): JSX.Element | null {
    const { warning, alertVisible } = useValues(eventsRetentionDeletionWarningLogic)
    const { snooze } = useActions(eventsRetentionDeletionWarningLogic)

    if (!warning || !alertVisible) {
        return null
    }

    if (isCollapsed) {
        return (
            <ButtonPrimitive
                iconOnly
                aria-label={warning.title}
                tooltip={warning.title}
                tooltipPlacement="right"
                onClick={() => router.actions.push(eventsRetentionSettingsUrl())}
                data-attr="nav-events-retention-deletion-warning"
            >
                <IconWarning className="text-warning" />
            </ButtonPrimitive>
        )
    }

    return (
        <LemonBanner type="warning" alignItems="start" className="mb-2 w-full text-xs" onClose={snooze}>
            <div className="font-semibold">{warning.title}</div>
            <div>{warning.description}</div>
            <Link to={eventsRetentionSettingsUrl()} data-attr="nav-events-retention-deletion-warning-settings">
                View retention settings
            </Link>
        </LemonBanner>
    )
}
