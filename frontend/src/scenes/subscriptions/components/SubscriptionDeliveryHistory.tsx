import { IconSend } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type {
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionApi,
    SubscriptionDeliveryApi,
} from '~/generated/core/api.schemas'
import {
    SubscriptionDeliveryStatusEnumApi,
    SubscriptionsDeliveriesListStatus as SubscriptionDeliveriesListStatusByValue,
} from '~/generated/core/api.schemas'

import { SubscriptionDeliveryDestinationCell } from './SubscriptionDestinationCell'
import { TARGET_TYPE_LABEL } from './subscriptionLabels'

/** API query `status` values; alias the const so Babel does not collide with the schema type of the same name. */
type DeliveryListStatusFilter =
    (typeof SubscriptionDeliveriesListStatusByValue)[keyof typeof SubscriptionDeliveriesListStatusByValue]

function deliveryStatusTag(status: SubscriptionDeliveryApi['status']): JSX.Element {
    let label: string
    let tagType: 'success' | 'danger' | 'warning' | 'default'
    switch (status) {
        case SubscriptionDeliveryStatusEnumApi.Starting:
            label = 'Starting'
            tagType = 'default'
            break
        case SubscriptionDeliveryStatusEnumApi.Completed:
            label = 'Completed'
            tagType = 'success'
            break
        case SubscriptionDeliveryStatusEnumApi.Failed:
            label = 'Failed'
            tagType = 'danger'
            break
        case SubscriptionDeliveryStatusEnumApi.Skipped:
            label = 'Skipped'
            tagType = 'warning'
            break
        default:
            label = status
            tagType = 'default'
    }
    return <LemonTag type={tagType}>{label}</LemonTag>
}

/** Matches `SubscriptionTriggerType` in Temporal (`scheduled`, `manual`, `target_change`). */
const DELIVERY_TRIGGER_LABELS: Record<string, string> = {
    scheduled: 'Scheduled',
    manual: 'Test delivery',
    target_change: 'Subscription updated',
}

function deliveryTriggerLabel(triggerType: string): string {
    const known = DELIVERY_TRIGGER_LABELS[triggerType]
    if (known) {
        return known
    }
    const spaced = triggerType.replace(/_/g, ' ').trim()
    if (!spaced) {
        return triggerType
    }
    return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase()
}

/** LemonTag and text cells share a row height; middle-align `td` so badges line up with copy. */
const DELIVERY_TABLE_CELL_CLASS = 'align-middle'

function buildDeliveryColumns(): LemonTableColumns<SubscriptionDeliveryApi> {
    return [
        {
            title: 'Created',
            key: 'created_at',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) => (
                <span className="whitespace-nowrap">
                    <TZLabel time={row.created_at} />
                </span>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) => deliveryStatusTag(row.status),
        },
        {
            title: 'Trigger',
            key: 'trigger_type',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) => <span className="whitespace-nowrap">{deliveryTriggerLabel(row.trigger_type)}</span>,
        },
        {
            title: 'Channel',
            key: 'target_type',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) => (
                <span className="whitespace-nowrap">
                    {TARGET_TYPE_LABEL[row.target_type as SubscriptionApi['target_type']] ?? row.target_type}
                </span>
            ),
        },
        {
            title: 'Destination',
            key: 'target_value',
            className: DELIVERY_TABLE_CELL_CLASS,
            style: () => ({ minWidth: '8rem', maxWidth: 0 }),
            render: (_v, row) => (
                <div className="min-w-0 w-full overflow-hidden">
                    <SubscriptionDeliveryDestinationCell targetType={row.target_type} targetValue={row.target_value} />
                </div>
            ),
        },
        {
            title: 'Scheduled',
            key: 'scheduled_at',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) =>
                row.scheduled_at ? (
                    <span className="whitespace-nowrap">
                        <TZLabel time={row.scheduled_at} />
                    </span>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: 'Finished',
            key: 'finished_at',
            className: DELIVERY_TABLE_CELL_CLASS,
            render: (_v, row) =>
                row.finished_at ? (
                    <span className="whitespace-nowrap">
                        <TZLabel time={row.finished_at} />
                    </span>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
    ]
}

const deliveryColumns = buildDeliveryColumns()

const DELIVERY_STATUS_FILTER_OPTIONS: { label: string; value: DeliveryListStatusFilter | null }[] = [
    { label: 'All statuses', value: null },
    { label: 'Starting', value: SubscriptionDeliveriesListStatusByValue.Starting },
    { label: 'Completed', value: SubscriptionDeliveriesListStatusByValue.Completed },
    { label: 'Failed', value: SubscriptionDeliveriesListStatusByValue.Failed },
    { label: 'Skipped', value: SubscriptionDeliveriesListStatusByValue.Skipped },
]

/** Mirrors `@posthog/quill-primitives` Empty layout (no table chrome). Icon tile uses app tokens (`bg-bg-light`) instead of `bg-muted`, which reads as a dark slab in this theme. */
function SubscriptionDeliveryHistoryQuillEmpty({
    onTestDelivery,
    testDeliveryLoading = false,
}: {
    onTestDelivery?: () => void
    testDeliveryLoading?: boolean
}): JSX.Element {
    return (
        <div
            data-slot="empty"
            className="flex w-full min-w-0 flex-1 flex-col items-center justify-center gap-4 rounded-xl border border-dashed p-6 text-center text-balance"
        >
            <div data-slot="empty-header" className="flex max-w-sm flex-col items-center gap-1">
                <div
                    data-slot="empty-icon"
                    data-variant="icon"
                    className="mb-2 flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-bg-light text-secondary [&_svg:not([class*='size-'])]:size-4"
                >
                    <IconSend />
                </div>
                <div data-slot="empty-title" className="text-sm font-medium tracking-tight">
                    No deliveries yet
                </div>
                <div
                    data-slot="empty-description"
                    className="text-xs/relaxed text-muted-foreground [&>a]:underline [&>a]:underline-offset-4 [&>a:hover]:text-primary"
                >
                    {onTestDelivery
                        ? 'Send a test delivery to verify this subscription and see it listed here.'
                        : 'Deliveries will show here after this subscription runs.'}
                </div>
            </div>
            {onTestDelivery ? (
                <div
                    data-slot="empty-content"
                    className="flex w-full max-w-sm min-w-0 flex-col items-center gap-2 text-xs/relaxed text-balance"
                >
                    <LemonButton
                        type="primary"
                        onClick={onTestDelivery}
                        loading={testDeliveryLoading}
                        disabledReason={testDeliveryLoading ? 'Sending test delivery…' : null}
                        data-attr="subscription-deliveries-empty-test-delivery"
                    >
                        Test delivery
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

export type SubscriptionDeliveryHistoryProps = {
    deliveriesPage: PaginatedSubscriptionDeliveryListApi | null
    deliveriesPageLoading: boolean
    loadDeliveriesPage: (targetUrl: string | null) => void
    deliveryStatusFilter?: DeliveryListStatusFilter | null
    onDeliveryStatusFilterChange?: (status: DeliveryListStatusFilter | null) => void
    /** When set, empty table shows this as the primary action (e.g. send a test delivery). */
    onTestDelivery?: () => void
    testDeliveryLoading?: boolean
}

export function SubscriptionDeliveryHistory({
    deliveriesPage,
    deliveriesPageLoading,
    loadDeliveriesPage,
    deliveryStatusFilter = null,
    onDeliveryStatusFilterChange,
    onTestDelivery,
    testDeliveryLoading = false,
}: SubscriptionDeliveryHistoryProps): JSX.Element {
    const rowCount = deliveriesPage?.results.length ?? 0
    const hasPagination = Boolean(deliveriesPage?.next || deliveriesPage?.previous)
    const showTable =
        deliveriesPageLoading ||
        rowCount > 0 ||
        hasPagination ||
        (deliveryStatusFilter != null && deliveriesPage != null)
    const showStatusFilter = Boolean(onDeliveryStatusFilterChange)
    const tableEmptyState = deliveryStatusFilter != null ? 'No deliveries match this filter' : 'No deliveries yet'

    return (
        <>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
                    <h2 className="text-lg font-semibold">Delivery history</h2>
                    {showTable && (showStatusFilter || onTestDelivery) ? (
                        <div className="flex flex-wrap items-center gap-3 shrink-0">
                            {onTestDelivery ? (
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    onClick={onTestDelivery}
                                    loading={testDeliveryLoading}
                                    disabledReason={testDeliveryLoading ? 'Sending test delivery…' : null}
                                    data-attr="subscription-detail-manual-deliver"
                                >
                                    Test delivery
                                </LemonButton>
                            ) : null}
                            {showStatusFilter ? (
                                <div className="flex items-center gap-2">
                                    <span className="text-sm text-secondary">Status</span>
                                    <LemonSelect<DeliveryListStatusFilter | null>
                                        size="small"
                                        options={DELIVERY_STATUS_FILTER_OPTIONS}
                                        value={deliveryStatusFilter}
                                        onChange={onDeliveryStatusFilterChange}
                                        data-attr="subscription-deliveries-status-filter"
                                    />
                                </div>
                            ) : null}
                        </div>
                    ) : null}
                </div>
                {showTable ? (
                    <LemonTable
                        dataSource={deliveriesPage?.results ?? []}
                        columns={deliveryColumns}
                        loading={deliveriesPageLoading}
                        loadingSkeletonRows={8}
                        rowKey="id"
                        nouns={['delivery', 'deliveries']}
                        emptyState={tableEmptyState}
                        data-attr="subscription-deliveries-table"
                        pagination={{
                            controlled: true,
                            pageSize: 50,
                            hideOnSinglePage: true,
                            onForward: deliveriesPage?.next
                                ? () => loadDeliveriesPage(deliveriesPage.next ?? null)
                                : undefined,
                            onBackward: deliveriesPage?.previous
                                ? () => loadDeliveriesPage(deliveriesPage.previous ?? null)
                                : undefined,
                        }}
                    />
                ) : (
                    <SubscriptionDeliveryHistoryQuillEmpty
                        onTestDelivery={onTestDelivery}
                        testDeliveryLoading={testDeliveryLoading}
                    />
                )}
            </div>
        </>
    )
}
