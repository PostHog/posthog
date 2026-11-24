import { IconNotification } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { destinationTypeLabel } from './destinations/platformAlertDestinations'
import { DestinationTypeEnumApi } from './generated/api.schemas'

const ICON_URLS: Partial<Record<DestinationTypeEnumApi, string>> = {
    slack: '/static/services/slack.png',
    teams: '/static/services/microsoft-teams.png',
    discord: '/static/services/discord.png',
    pagerduty: '/static/services/pagerduty.png',
    webhook: '/static/services/webhook.svg',
}

export function PlatformAlertDestinationIcons({
    types,
    enabled,
}: {
    types: readonly DestinationTypeEnumApi[]
    enabled: boolean
}): JSX.Element {
    if (!types.length) {
        // Only a warning, not an error: team-wide routes or unconverted HogFunctions can still notify.
        return <span className={enabled ? 'text-warning' : 'text-muted'}>No direct destinations</span>
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {types.map((type) => {
                const label = destinationTypeLabel(type)
                const iconUrl = ICON_URLS[type]
                return (
                    <Tooltip key={type} title={label}>
                        <LemonTag role="img" aria-label={label} data-attr={`platform-alert-destination-${type}`}>
                            {iconUrl ? (
                                <img src={iconUrl} alt="" className="size-3.5 rounded-sm object-contain" />
                            ) : (
                                <IconNotification className="text-sm" />
                            )}
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
