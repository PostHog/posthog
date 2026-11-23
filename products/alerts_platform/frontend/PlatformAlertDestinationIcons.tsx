import { IconNotification } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

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
        // An enabled alert that notifies nobody is a likely mistake. A disabled one is not.
        return <span className={enabled ? 'text-warning' : 'text-muted'}>None</span>
    }
    const counts = new Map<DestinationTypeEnumApi, number>()
    for (const type of types) {
        counts.set(type, (counts.get(type) ?? 0) + 1)
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {[...counts].map(([type, count]) => {
                const label = destinationTypeLabel(type)
                const iconUrl = ICON_URLS[type]
                const title = count > 1 ? `${count} ${label}` : label
                return (
                    <Tooltip key={type} title={title}>
                        <span
                            className="flex h-[22px] items-center gap-1 rounded border border-primary px-1 text-xs text-secondary"
                            role="img"
                            aria-label={title}
                            data-attr={`platform-alert-destination-${type}`}
                        >
                            {iconUrl ? (
                                <img src={iconUrl} alt="" className="size-3.5 rounded-sm object-contain" />
                            ) : (
                                <IconNotification className="text-sm" />
                            )}
                            {count > 1 && <span>{count}</span>}
                        </span>
                    </Tooltip>
                )
            })}
        </div>
    )
}
