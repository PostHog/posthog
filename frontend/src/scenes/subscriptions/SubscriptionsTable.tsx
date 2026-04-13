import { LemonTable, LemonTableColumn, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'
import type { PaginationManual, Sorting } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { atColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { TargetTypeEnumApi } from '~/generated/core/api.schemas'
import type { InsightShortId } from '~/types'

import { SubscriptionDestinationCell } from './SubscriptionDestinationCell'

const TARGET_TYPE_LABEL: Record<SubscriptionApi['target_type'], string> = {
    [TargetTypeEnumApi.Email]: 'Email',
    [TargetTypeEnumApi.Slack]: 'Slack',
    [TargetTypeEnumApi.Webhook]: 'Webhook',
}

export function subscriptionName(sub: SubscriptionApi): string {
    return sub.title?.trim() || sub.resource_name?.trim() || 'Untitled subscription'
}

/** URL to view the insight or dashboard this subscription is attached to (not the subscription edit UI). */
export function subscriptionResourceViewUrl(sub: SubscriptionApi): string | null {
    if (sub.insight && sub.insight_short_id) {
        return urls.insightView(sub.insight_short_id as InsightShortId)
    }
    if (sub.dashboard) {
        return urls.dashboard(sub.dashboard)
    }
    return null
}

function subscriptionResourceLinkLabel(sub: SubscriptionApi): string {
    const name = sub.resource_name?.trim()
    if (name) {
        return name
    }
    if (sub.insight) {
        return 'Insight'
    }
    if (sub.dashboard) {
        return 'Dashboard'
    }
    return 'View'
}

function buildColumns(renderRowActions: (sub: SubscriptionApi) => JSX.Element): LemonTableColumns<SubscriptionApi> {
    return [
        {
            title: 'Name',
            key: 'name',
            // td only (th does not use column.style): truncate; minWidth beats maxWidth:0 so column stays ≥100px
            style: () => ({
                minWidth: '200px',
                maxWidth: 0,
            }),
            sorter: true,
            render: (_value: unknown, sub: SubscriptionApi) => {
                const name = subscriptionName(sub)
                return (
                    <Tooltip title={name}>
                        <div className="min-w-0 w-full overflow-hidden">
                            <span className="font-medium block truncate">{name}</span>
                        </div>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Type',
            key: 'type',
            width: '7rem',
            render: (_value: unknown, sub: SubscriptionApi) => (
                <span className="whitespace-nowrap">{sub.insight ? 'Insight' : sub.dashboard ? 'Dashboard' : '—'}</span>
            ),
        },
        {
            title: 'Resource',
            key: 'resource',
            style: () => ({
                minWidth: '8rem',
                maxWidth: 0,
            }),
            render: (_value: unknown, sub: SubscriptionApi) => {
                const href = subscriptionResourceViewUrl(sub)
                if (!href) {
                    return <span className="text-secondary">—</span>
                }
                const label = subscriptionResourceLinkLabel(sub)
                return (
                    <Tooltip title={label}>
                        <div className="min-w-0 w-full overflow-hidden">
                            <Link
                                to={href}
                                className="font-medium block truncate"
                                data-attr="subscription-resource-link"
                            >
                                {label}
                            </Link>
                        </div>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Channel',
            key: 'target_type',
            render: (_value: unknown, sub: SubscriptionApi) => (
                <span className="whitespace-nowrap">{TARGET_TYPE_LABEL[sub.target_type] ?? sub.target_type}</span>
            ),
        },
        {
            title: 'Destination',
            key: 'target_value',
            render: (_value: unknown, sub: SubscriptionApi) => <SubscriptionDestinationCell sub={sub} />,
        },
        {
            title: 'Recurrence',
            key: 'summary',
            dataIndex: 'summary',
            render: (_value: unknown, sub: SubscriptionApi) => sub.summary || '—',
        },
        {
            title: 'Next delivery',
            key: 'next_delivery_date',
            dataIndex: 'next_delivery_date',
            align: 'right',
            sorter: true,
            defaultSortOrder: 1,
            render: (_value: unknown, sub: SubscriptionApi) =>
                sub.next_delivery_date ? (
                    <div className="whitespace-nowrap">
                        <TZLabel time={sub.next_delivery_date} />
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            ...(createdByColumn() as unknown as LemonTableColumn<SubscriptionApi, 'created_by'>),
            sorter: true,
        } as LemonTableColumn<SubscriptionApi, keyof SubscriptionApi | undefined>,
        {
            ...(atColumn<SubscriptionApi>('created_at', 'Created') as LemonTableColumn<
                SubscriptionApi,
                keyof SubscriptionApi | undefined
            >),
            sorter: true,
        },
        {
            width: 56,
            align: 'right',
            className: 'pl-6',
            render: (_value: unknown, sub: SubscriptionApi) => renderRowActions(sub),
        },
    ]
}

export interface SubscriptionsTableProps {
    dataSource: SubscriptionApi[]
    loading?: boolean
    pagination?: PaginationManual
    sorting?: Sorting | null
    onSort?: (sorting: Sorting | null) => void
    renderRowActions: (sub: SubscriptionApi) => JSX.Element
}

export function SubscriptionsTable({
    dataSource,
    loading,
    pagination,
    sorting,
    onSort,
    renderRowActions,
}: SubscriptionsTableProps): JSX.Element {
    const columns = buildColumns(renderRowActions)

    return (
        <LemonTable
            dataSource={dataSource}
            columns={columns}
            loading={loading}
            loadingSkeletonRows={8}
            rowKey="id"
            pagination={pagination}
            nouns={['subscription', 'subscriptions']}
            emptyState="No subscriptions match your filters"
            sorting={sorting}
            onSort={onSort}
            // Kea + API `ordering` own sort; LemonTable URL `order` would diverge from subscriptionsSceneLogic on reload.
            useURLForSorting={false}
            data-attr="subscriptions-table"
        />
    )
}
