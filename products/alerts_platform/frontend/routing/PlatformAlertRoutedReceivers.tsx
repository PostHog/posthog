import { useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import type { AlertRouteMatchApi } from '../generated/api.schemas'
import { platformAlertRoutedReceiversLogic } from './platformAlertRoutedReceiversLogic'
import { receiverTarget, receiverTypeLabel, routeEventKindsLabel, routingUrl } from './platformAlertRoutingFormat'
import { RouteMatcherTags } from './RouteMatcherTags'

/** The team-wide receivers an alert with these labels also sends to, through the routes they match. */
export function PlatformAlertRoutedReceivers({ labels }: { labels: Record<string, string> }): JSX.Element {
    const { matches, matchesLoading } = useValues(platformAlertRoutedReceiversLogic({ labels }))

    if (!matchesLoading && matches === null) {
        return (
            <LemonBanner type="warning">
                Couldn't load routing. Reading it needs access to every alert source in this project.
            </LemonBanner>
        )
    }

    const columns: LemonTableColumns<AlertRouteMatchApi> = [
        {
            title: 'Matches',
            render: (_, { route }) => <RouteMatcherTags matchers={route.matchers} />,
        },
        {
            title: 'Sends to',
            render: (_, { receiver }) => (
                <div className="flex flex-col">
                    <Link to={routingUrl({ receiver: receiver.id })} data-attr="platform-alert-routed-receiver-link">
                        {receiver.name}
                    </Link>
                    <span className="font-mono text-xs text-secondary break-all">
                        {receiverTypeLabel(receiver.type)} · {receiverTarget(receiver)}
                    </span>
                </div>
            ),
        },
        {
            title: 'Events',
            render: (_, { route }) => routeEventKindsLabel(route.event_kinds),
        },
        {
            width: 0,
            render: (_, { route }) => (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    className="whitespace-nowrap"
                    to={routingUrl({ route: route.id })}
                    data-attr="platform-alert-routed-route-link"
                >
                    View route
                </LemonButton>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={matches ?? []}
            columns={columns}
            loading={matchesLoading}
            rowKey={({ route }) => route.id}
            emptyState="No route matches this alert's labels."
            data-attr="platform-alert-routed-receivers"
        />
    )
}
