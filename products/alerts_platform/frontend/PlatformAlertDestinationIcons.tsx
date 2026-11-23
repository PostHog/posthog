import { IconNotification } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { DestinationTypeEnumApi } from './generated/api.schemas'

const DESTINATION_TYPES: Partial<Record<DestinationTypeEnumApi, { label: string; iconUrl: string }>> = {
    slack: { label: 'Slack', iconUrl: '/static/services/slack.png' },
    teams: { label: 'Microsoft Teams', iconUrl: '/static/services/microsoft-teams.png' },
    discord: { label: 'Discord', iconUrl: '/static/services/discord.png' },
    pagerduty: { label: 'PagerDuty', iconUrl: '/static/services/pagerduty.png' },
    webhook: { label: 'Webhook', iconUrl: '/static/services/webhook.svg' },
}

export function PlatformAlertDestinationIcons({ types }: { types: readonly DestinationTypeEnumApi[] }): JSX.Element {
    if (!types.length) {
        return <span className="text-muted">None</span>
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {[...new Set(types)].map((type) => {
                const known = DESTINATION_TYPES[type]
                return (
                    <Tooltip key={type} title={known?.label ?? type}>
                        <span className="flex" data-attr={`platform-alert-destination-${type}`}>
                            {known ? (
                                <img src={known.iconUrl} alt={known.label} className="size-4 object-contain" />
                            ) : (
                                <IconNotification className="text-base text-muted" role="img" aria-label={type} />
                            )}
                        </span>
                    </Tooltip>
                )
            })}
        </div>
    )
}
