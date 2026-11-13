import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSwitch, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { AlertRouteApi } from '../generated/api.schemas'
import { routeEventKindsLabel } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'
import { RouteMatcherTags } from './RouteMatcherTags'

export function PlatformAlertRoutesTable(): JSX.Element {
    const { routes, routesLoading, receivers, receiversById, togglingIds, editDisabledReason } =
        useValues(platformAlertRoutingLogic)
    const { openRouteModal, deleteRoute, setRouteEnabled } = useActions(platformAlertRoutingLogic)
    const { searchParams } = useValues(router)

    const columns: LemonTableColumns<AlertRouteApi> = [
        {
            title: 'Matches',
            render: (_, route) => <RouteMatcherTags matchers={route.matchers} />,
        },
        {
            title: 'Sends to',
            render: (_, route) =>
                receivers === null ? null : (receiversById[route.receiver_id]?.name ?? 'Unknown receiver'),
        },
        {
            title: 'Events',
            render: (_, route) => routeEventKindsLabel(route.event_kinds),
        },
        {
            title: 'Enabled',
            render: (_, route) => (
                <LemonSwitch
                    checked={route.enabled}
                    onChange={(enabled) => setRouteEnabled(route, enabled)}
                    disabledReason={editDisabledReason ?? (togglingIds.includes(route.id) ? 'Saving…' : null)}
                    data-attr="platform-alert-route-enabled"
                />
            ),
        },
        {
            width: 0,
            render: (_, route) => (
                <More
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Edit',
                                    onClick: () => openRouteModal(route),
                                    disabledReason: editDisabledReason,
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteRoute(route),
                                    disabledReason: editDisabledReason,
                                },
                            ]}
                        />
                    }
                    data-attr="platform-alert-route-more"
                />
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={routes ?? []}
            columns={columns}
            loading={routesLoading || routes === null}
            rowKey="id"
            rowStatus={(route) => (route.id === searchParams.route ? 'highlighted' : null)}
            emptyState="No routes yet. Alerts send only to their own destinations."
        />
    )
}
