import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { AlertRouteApi } from '../generated/api.schemas'
import { ALL_ROUTE_EVENT_KINDS, ROUTE_EVENT_KIND_OPTIONS } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function PlatformAlertRoutesTable(): JSX.Element {
    const { routes, routesLoading, receivers, receiversById, togglingIds, editDisabledReason } =
        useValues(platformAlertRoutingLogic)
    const { openRouteModal, deleteRoute, setRouteEnabled } = useActions(platformAlertRoutingLogic)

    const columns: LemonTableColumns<AlertRouteApi> = [
        {
            title: 'Matches',
            render: (_, route) =>
                route.matchers.length ? (
                    <div className="flex flex-wrap gap-1" translate="no">
                        {route.matchers.map((matcher) => (
                            <LemonTag key={matcher.label} className="font-mono">
                                {`${matcher.label} = ${matcher.value}`}
                            </LemonTag>
                        ))}
                    </div>
                ) : (
                    <LemonTag type="warning">All alerts</LemonTag>
                ),
        },
        {
            title: 'Sends to',
            render: (_, route) =>
                receivers === null ? null : (receiversById[route.receiver_id]?.name ?? 'Unknown receiver'),
        },
        {
            title: 'Events',
            render: (_, route) => {
                const kinds = route.event_kinds
                return kinds.length === ALL_ROUTE_EVENT_KINDS.length
                    ? 'All'
                    : ROUTE_EVENT_KIND_OPTIONS.filter((option) => kinds.includes(option.value))
                          .map((option) => option.label)
                          .join(', ')
            },
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
            emptyState="No routes yet. Alerts send only to their own destinations."
        />
    )
}
