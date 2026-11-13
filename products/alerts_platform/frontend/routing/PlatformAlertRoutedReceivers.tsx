import { useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { platformAlertRoutedReceiversLogic } from './platformAlertRoutedReceiversLogic'
import { ROUTE_EVENT_KIND_OPTIONS, receiverTarget, receiverTypeLabel } from './platformAlertRoutingFormat'

const ROUTING_URL = `${urls.platformAlerts()}?tab=routing`

/** The team-wide receivers an alert with these labels also sends to, through the routes they match. */
export function PlatformAlertRoutedReceivers({ labels }: { labels: Record<string, string> }): JSX.Element {
    const { matches, matchesLoading } = useValues(platformAlertRoutedReceiversLogic({ labels }))

    if (matchesLoading && matches === null) {
        return <Spinner />
    }
    if (matches === null) {
        return (
            <LemonBanner type="warning">
                Couldn't load routing. Reading it needs access to every alert source in this project.
            </LemonBanner>
        )
    }
    if (matches.length === 0) {
        return (
            <p className="m-0 text-secondary">
                No route matches this alert's labels. <Link to={ROUTING_URL}>Manage routing</Link>
            </p>
        )
    }
    return (
        <ul className="flex flex-col gap-2 m-0 p-0 list-none" data-attr="platform-alert-routed-receivers">
            {matches.map(({ route, receiver }) => (
                <li key={route.id} className="flex flex-col gap-0.5">
                    <span>
                        <span className="font-semibold">{receiver.name}</span>
                        <span className="text-secondary">
                            {' '}
                            · {receiverTypeLabel(receiver.type)} {receiverTarget(receiver)}
                        </span>
                    </span>
                    <span className="text-secondary text-xs">
                        {route.matchers.length === 0
                            ? 'Matches every alert'
                            : `Matches ${route.matchers.map((m) => `${m.label} = ${m.value}`).join(', ')}`}
                        {' · '}
                        {ROUTE_EVENT_KIND_OPTIONS.filter((o) => route.event_kinds.includes(o.value))
                            .map((o) => o.label)
                            .join(', ')}
                    </span>
                </li>
            ))}
        </ul>
    )
}
