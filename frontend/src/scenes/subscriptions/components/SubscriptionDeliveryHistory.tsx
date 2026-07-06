import { IconSend, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'
import type {
    AIReportQueryDiagnosticApi,
    PaginatedSubscriptionDeliveryListApi,
    SubscriptionApi,
    SubscriptionDeliveryApi,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'
import {
    SubscriptionDeliveryStatusEnumApi,
    SubscriptionsDeliveriesListStatus as SubscriptionDeliveriesListStatusByValue,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { DeliveryFeedback } from '../subscriptionSceneLogic'
import { SubscriptionDeliveryDestinationCell } from './SubscriptionDestinationCell'
import { TARGET_TYPE_LABEL } from './subscriptionLabels'

/** API query `status` values; alias the const so Babel does not collide with the schema type of the same name. */
type DeliveryListStatusFilter =
    (typeof SubscriptionDeliveriesListStatusByValue)[keyof typeof SubscriptionDeliveriesListStatusByValue]

function deliveryStatusTag(row: SubscriptionDeliveryApi): JSX.Element {
    let label: string
    let tagType: 'success' | 'danger' | 'warning' | 'default'
    switch (row.status) {
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
            label = row.status
            tagType = 'default'
    }
    const failureMessage = (row.error as { message?: unknown } | null)?.message
    if (
        row.status === SubscriptionDeliveryStatusEnumApi.Failed &&
        typeof failureMessage === 'string' &&
        failureMessage
    ) {
        return (
            <Tooltip title={failureMessage}>
                <LemonTag type={tagType} className="cursor-help">
                    {label}
                </LemonTag>
            </Tooltip>
        )
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

/**
 * All per-query diagnostics for an AI-prompt delivery (succeeded and failed). The backend scrubs
 * this to `null` for callers without `query:viewer` access, so it is empty unless the viewer may see
 * query content. Surfacing the successful queries — not just the failed ones — lets a subscription
 * owner see exactly what the prompt generated and self-recover by tightening it.
 */
function reportDiagnostics(row: SubscriptionDeliveryApi): readonly AIReportQueryDiagnosticApi[] {
    return row.ai_report_diagnostics ?? []
}

function queryStatusTag(d: AIReportQueryDiagnosticApi): JSX.Element {
    return d.ok === false ? (
        <LemonTag type="danger">{d.error_type || 'Failed'}</LemonTag>
    ) : (
        <LemonTag type="success">OK</LemonTag>
    )
}

function diagnosticsSummary(diagnostics: readonly AIReportQueryDiagnosticApi[]): string {
    const total = diagnostics.length
    const failed = diagnostics.filter((d) => d.ok === false).length
    const noun = total === 1 ? 'query' : 'queries'
    return failed === 0 ? `${total} ${noun} · all succeeded` : `${total} ${noun} · ${failed} failed`
}

const failedIndexes = (diagnostics: readonly AIReportQueryDiagnosticApi[]): number[] =>
    diagnostics.map((d, i) => (d.ok === false ? i : -1)).filter((i) => i >= 0)

/** The delivered report markdown, when present. Scrubbed to `null` for callers without
 * `query:viewer` access just like the diagnostics. */
function reportMarkdown(row: SubscriptionDeliveryApi): string | null {
    const report = row.ai_report
    return typeof report === 'string' && report ? report : null
}

/** The subscription prompt captured when this report was generated. User-authored (not query-derived),
 * so it stays readable even for callers without query access. */
function reportPrompt(row: SubscriptionDeliveryApi): string | null {
    const prompt = row.ai_report_prompt
    return typeof prompt === 'string' && prompt ? prompt : null
}

/**
 * Per-query accordion: one compact header per generated query (status + description); expand a query for its
 * SQL. Failed queries are open by default so a degraded report stays loud and debuggable.
 */
function GeneratedQueries({ diagnostics }: { diagnostics: readonly AIReportQueryDiagnosticApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="text-secondary">{diagnosticsSummary(diagnostics)}</div>
            <LemonCollapse
                size="small"
                multiple
                defaultActiveKeys={failedIndexes(diagnostics)}
                panels={diagnostics.map((d, index) => ({
                    key: index,
                    header: (
                        <div className="flex items-center gap-2">
                            {queryStatusTag(d)}
                            <span>{d.description || 'Query'}</span>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-2">
                            {d.error_message ? <div className="text-danger">{d.error_message}</div> : null}
                            {d.hogql ? (
                                <CodeSnippet language={Language.SQL} compact>
                                    {d.hogql}
                                </CodeSnippet>
                            ) : (
                                <span className="text-secondary">No query captured.</span>
                            )}
                        </div>
                    ),
                }))}
            />
        </div>
    )
}

function ExpandedDeliveryRow({ row }: { row: SubscriptionDeliveryApi }): JSX.Element | null {
    const diagnostics = reportDiagnostics(row)
    const report = reportMarkdown(row)
    const prompt = reportPrompt(row)
    if (!row.change_summary && !report && !prompt && diagnostics.length === 0) {
        return null
    }
    return (
        <div className="px-4 py-3 text-sm flex flex-col gap-4">
            {row.change_summary ? (
                <div className="whitespace-pre-wrap">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1">AI summary</div>
                    {row.change_summary}
                </div>
            ) : null}
            {prompt ? (
                <div className="whitespace-pre-wrap">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1">
                        Prompt at time of generation
                    </div>
                    {prompt}
                </div>
            ) : null}
            {report ? (
                <div className="flex flex-col gap-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Delivered report</div>
                    <div className="max-h-96 overflow-auto rounded border bg-bg-light p-3">
                        <LemonMarkdown>{report}</LemonMarkdown>
                    </div>
                </div>
            ) : null}
            {diagnostics.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">
                        Generated queries
                    </div>
                    <GeneratedQueries diagnostics={diagnostics} />
                </div>
            ) : null}
        </div>
    )
}

// Module-scope const keeps the reference stable across parent re-renders.
const DELIVERY_TABLE_EXPANDABLE = {
    rowExpandable: (row: SubscriptionDeliveryApi) =>
        Boolean(row.change_summary) ||
        Boolean(reportMarkdown(row)) ||
        Boolean(reportPrompt(row)) ||
        reportDiagnostics(row).length > 0,
    expandedRowRender: (row: SubscriptionDeliveryApi) => <ExpandedDeliveryRow row={row} />,
}

// Only called from storybook visual tests — production use ignores the optional set.
function buildExpandable(initiallyExpandedIds?: ReadonlySet<string>): typeof DELIVERY_TABLE_EXPANDABLE & {
    isRowExpanded?: (row: SubscriptionDeliveryApi) => number
} {
    if (!initiallyExpandedIds || initiallyExpandedIds.size === 0) {
        return DELIVERY_TABLE_EXPANDABLE
    }
    return {
        ...DELIVERY_TABLE_EXPANDABLE,
        isRowExpanded: (row) => (initiallyExpandedIds.has(row.id) ? 1 : -1),
    }
}

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
            render: (_v, row) => deliveryStatusTag(row),
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

function buildFeedbackColumn(
    deliveryFeedback: Record<string, DeliveryFeedback>,
    recentlyThankedDeliveries: Record<string, true>,
    onDeliveryFeedback: (deliveryId: string, feedback: DeliveryFeedback) => void
): LemonTableColumns<SubscriptionDeliveryApi>[number] {
    return {
        title: 'Useful?',
        key: 'feedback',
        className: DELIVERY_TABLE_CELL_CLASS,
        render: (_v, row) => {
            if (row.status !== SubscriptionDeliveryStatusEnumApi.Completed) {
                return <span className="text-secondary">—</span>
            }
            if (recentlyThankedDeliveries[row.id]) {
                return <span className="text-secondary whitespace-nowrap">Thanks!</span>
            }
            // Recorded feedback highlights the chosen side; clicking the other side switches the vote
            // (analysis takes the latest event per person + delivery, so switching just wins).
            const recorded = deliveryFeedback[row.id]
            return (
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        icon={<IconThumbsUp />}
                        active={recorded === 'positive'}
                        tooltip={
                            recorded === 'positive' ? 'You marked this report as useful' : 'This report was useful'
                        }
                        onClick={recorded === 'positive' ? undefined : () => onDeliveryFeedback(row.id, 'positive')}
                        data-attr="subscription-delivery-feedback-positive"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconThumbsDown />}
                        active={recorded === 'negative'}
                        tooltip={
                            recorded === 'negative'
                                ? 'You marked this report as not useful'
                                : 'This report was not useful'
                        }
                        onClick={recorded === 'negative' ? undefined : () => onDeliveryFeedback(row.id, 'negative')}
                        data-attr="subscription-delivery-feedback-negative"
                    />
                </div>
            )
        },
    }
}

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
    /** When set (AI-prompt subscriptions), completed rows show thumbs up/down feedback buttons. */
    onDeliveryFeedback?: (deliveryId: string, feedback: DeliveryFeedback) => void
    /** Feedback already recorded (persisted per browser), keyed by delivery id — those rows show the chosen option. */
    deliveryFeedback?: Record<string, DeliveryFeedback>
    /** Deliveries thanked moments ago — those rows briefly show "Thanks!" before settling into the chosen option. */
    recentlyThankedDeliveries?: Record<string, true>
    /**
     * STORYBOOK-ONLY: delivery ids whose AI summary row should render pre-expanded
     * on first render. Used exclusively by visual regression tests to capture the
     * expanded-row state; production callers should not pass this prop.
     */
    __storyOnlyInitiallyExpandedDeliveryIds?: ReadonlySet<string>
}

export function SubscriptionDeliveryHistory({
    deliveriesPage,
    deliveriesPageLoading,
    loadDeliveriesPage,
    deliveryStatusFilter = null,
    onDeliveryStatusFilterChange,
    onTestDelivery,
    testDeliveryLoading = false,
    onDeliveryFeedback,
    deliveryFeedback = {},
    recentlyThankedDeliveries = {},
    __storyOnlyInitiallyExpandedDeliveryIds,
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
    const expandable = buildExpandable(__storyOnlyInitiallyExpandedDeliveryIds)
    const columns = onDeliveryFeedback
        ? [...deliveryColumns, buildFeedbackColumn(deliveryFeedback, recentlyThankedDeliveries, onDeliveryFeedback)]
        : deliveryColumns

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
                        columns={columns}
                        loading={deliveriesPageLoading}
                        loadingSkeletonRows={8}
                        rowKey="id"
                        nouns={['delivery', 'deliveries']}
                        emptyState={tableEmptyState}
                        data-attr="subscription-deliveries-table"
                        expandable={expandable}
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
