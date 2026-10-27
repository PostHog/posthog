import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import type { BulkSelectionConfig } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { METRIC_BULK_MAX, compareText, humanizeDefinitionKind, metricCount, reportCatalogTableSorted } from '../common'
import { CatalogExplainer } from '../components/CatalogExplainer'
import { LifecycleStrip } from '../components/LifecycleStrip'
import { MetricOwnerSelect } from '../components/MetricOwnerSelect'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { BulkMetricAction, MetricStatusFilter, metricsLogic } from '../metricsLogic'

const STATUS_FILTER_OPTIONS: { value: MetricStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'approved', label: 'Approved' },
]

const BULK_BAR_CLASS =
    'sticky bottom-4 z-10 self-center w-fit rounded border border-primary bg-surface-primary px-2 py-1 shadow empty:hidden'

const LOAD_FAILED = 'Could not load metrics. Reload the list to try again.'

const OVER_CAP_REASON = `Select at most ${METRIC_BULK_MAX} metrics at a time`

function isApprovable(metric: DataCatalogMetricApi): boolean {
    return metric.status !== 'approved' && !metric.is_drifted
}

function StatusTag({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <LemonTag type={metric.status === 'approved' ? 'success' : 'warning'}>{metric.status}</LemonTag>
            {metric.is_drifted && <LemonTag type="danger">Drifted</LemonTag>}
        </div>
    )
}

function SourceTag({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    if (metric.created_source !== 'ai_generated') {
        return <span className="text-secondary">User</span>
    }
    const confidencePercent = metric.confidence != null ? `${Math.round(metric.confidence * 100)}%` : 'unknown'
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>Confidence: {confidencePercent}</span>
                    {metric.ai_model && <span>Model: {metric.ai_model}</span>}
                    {metric.reasoning && <span>{metric.reasoning}</span>}
                </div>
            }
        >
            <LemonTag type="completion">AI</LemonTag>
        </Tooltip>
    )
}

export function MetricsTab(): JSX.Element {
    // State, not a ref, so the table re-renders once the slot mounts and the bar can portal into it.
    // The bar portals below the table instead of above it, so selecting a row never shifts the rows.
    const [bulkBarTarget, setBulkBarTarget] = useState<HTMLDivElement | null>(null)
    const [approvedBulkBarTarget, setApprovedBulkBarTarget] = useState<HTMLDivElement | null>(null)
    const {
        metrics,
        allMetrics,
        allMetricsLoading,
        filters,
        actionsInFlight,
        bulkActionInFlight,
        ownerFilterOptions,
        stageCounts,
        reviewQueue,
        approvedMetrics,
        metricsLoadState,
    } = useValues(metricsLogic)
    const {
        setFilters,
        toggleStage,
        loadMetrics,
        approveMetric,
        refreshMetricFromInsight,
        deleteMetric,
        setMetricOwner,
        bulkApproveMetrics,
        bulkDeleteMetrics,
        bulkChangeMetricOwner,
    } = useActions(metricsLogic)

    const reviewQueueEnabled = useFeatureFlag('DATA_CATALOG_REVIEW_QUEUE')

    const bulkBusyReason = bulkActionInFlight ? 'A bulk action is running' : undefined
    // Reload replaces the whole list and takes no breakpoint, so a load that resolves after a
    // mutation would repaint pre-mutation rows (e.g. bring back rows a bulk delete just removed).
    // Block it while any mutation is in flight; the view is authoritative again on the next load.
    const reloadDisabledReason =
        bulkBusyReason ?? (Object.values(actionsInFlight).some(Boolean) ? 'A metric action is running' : undefined)
    // An empty queue is a verdict about loaded data, so stay in the skeleton until the first load answers.
    const tableLoading = allMetricsLoading || metricsLoadState === 'unknown'
    // A drifted approved metric sits in the queue, so the queue stays visible under the Approved stage when it holds one.
    const showReviewQueue = filters.status !== 'approved' || reviewQueue.length > 0
    const showApproved = filters.status === 'all' || filters.status === 'approved'
    const otherBulkActionReason = (self: BulkMetricAction): string | undefined =>
        bulkActionInFlight && bulkActionInFlight !== self ? 'Another bulk action is running' : undefined

    const bulkApproveDisabledReason = (approvableCount: number): string | undefined => {
        if (approvableCount === 0) {
            return 'Every selected metric is already approved or has drifted. Refresh a drifted metric first.'
        }
        if (approvableCount > METRIC_BULK_MAX) {
            return OVER_CAP_REASON
        }
        return otherBulkActionReason('approve')
    }

    const bulkSelectionDisabledReason = (selectedCount: number, self: BulkMetricAction): string | undefined => {
        if (selectedCount === 0) {
            return 'The selected metrics are no longer available. Reload the list.'
        }
        if (selectedCount > METRIC_BULK_MAX) {
            return OVER_CAP_REASON
        }
        return otherBulkActionReason(self)
    }

    const confirmDelete = (metric: DataCatalogMetricApi): void => {
        LemonDialog.open({
            title: 'Delete metric?',
            content: (
                <div className="text-sm text-secondary">
                    This deletes {metric.name} and makes its name available for a new metric. Queries and links that
                    reference it will stop working.
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => deleteMetric(metric.name),
            },
            secondaryButton: { children: 'Cancel', type: 'tertiary' },
        })
    }

    const confirmBulkDelete = (names: string[], onDeleted: () => void): void => {
        LemonDialog.open({
            title: `Delete ${metricCount(names.length)}?`,
            content: (
                <div className="text-sm text-secondary">
                    This deletes the selected metrics and makes their names available for new metrics. Queries and links
                    that reference them will stop working.
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => bulkDeleteMetrics(names, onDeleted),
            },
            secondaryButton: { children: 'Cancel', type: 'tertiary' },
        })
    }

    const baseColumns: LemonTableColumns<DataCatalogMetricApi> = [
        {
            title: 'Name',
            key: 'name',
            dataIndex: 'name',
            render: (_, metric) => (
                <LemonTableLink
                    to={urls.dataCatalogMetric(metric.name)}
                    title={metric.display_name || metric.name}
                    // Render descriptions with images disabled so a stored image URL can't beacon other viewers.
                    description={
                        metric.description ? (
                            <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings disableImages>
                                {metric.description}
                            </LemonMarkdown>
                        ) : undefined
                    }
                />
            ),
            sorter: (a, b) => compareText(a.display_name || a.name, b.display_name || b.name),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, metric) => <StatusTag metric={metric} />,
            sorter: (a, b) => compareText(a.status, b.status) || Number(a.is_drifted) - Number(b.is_drifted),
        },
        {
            title: 'Definition',
            key: 'definition_kind',
            render: (_, metric) => <LemonTag type="option">{humanizeDefinitionKind(metric.definition_kind)}</LemonTag>,
            sorter: (a, b) =>
                compareText(humanizeDefinitionKind(a.definition_kind), humanizeDefinitionKind(b.definition_kind)),
        },
        {
            title: 'Source',
            key: 'created_source',
            render: (_, metric) => <SourceTag metric={metric} />,
            sorter: (a, b) => compareText(a.created_source, b.created_source),
        },
        {
            title: 'Owner',
            key: 'owner',
            render: (_, metric) => (
                <MetricOwnerSelect
                    owner={metric.owner}
                    loading={!!actionsInFlight[metric.name]}
                    disabledReason={bulkBusyReason}
                    onChange={(owner) => setMetricOwner(metric.name, owner)}
                />
            ),
            sorter: (a, b) => compareText(a.owner, b.owner),
        },
        createdAtColumn<DataCatalogMetricApi>() as LemonTableColumns<DataCatalogMetricApi>[number],
    ]

    const menuColumn: LemonTableColumns<DataCatalogMetricApi>[number] = {
        key: 'actions',
        width: 0,
        render: (_, metric) => {
            const inFlight = !!actionsInFlight[metric.name]
            return (
                <More
                    overlay={
                        <>
                            {metric.status !== 'approved' && (
                                <LemonButton
                                    fullWidth
                                    loading={inFlight}
                                    disabledReason={
                                        bulkBusyReason ??
                                        (metric.is_drifted
                                            ? 'This metric has drifted from its source insight. Refresh it first.'
                                            : undefined)
                                    }
                                    onClick={() => approveMetric(metric.name)}
                                >
                                    Approve
                                </LemonButton>
                            )}
                            {metric.source_insight_short_id && (
                                <LemonButton
                                    fullWidth
                                    loading={inFlight}
                                    disabledReason={bulkBusyReason}
                                    onClick={() => refreshMetricFromInsight(metric.name)}
                                >
                                    Refresh from insight
                                </LemonButton>
                            )}
                            <LemonButton
                                fullWidth
                                status="danger"
                                disabledReason={bulkBusyReason ?? (inFlight ? 'Working' : undefined)}
                                onClick={() => confirmDelete(metric)}
                            >
                                Delete
                            </LemonButton>
                        </>
                    }
                />
            )
        },
    }

    // The queue puts the next step on the row. Delete stays in a menu, away from the primary action.
    const reviewActionsColumn: LemonTableColumns<DataCatalogMetricApi>[number] = {
        key: 'actions',
        width: 0,
        render: (_, metric) => {
            const inFlight = !!actionsInFlight[metric.name]
            return (
                <div className="flex items-center justify-end gap-1">
                    {metric.is_drifted ? (
                        metric.source_insight_short_id && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                loading={inFlight}
                                disabledReason={bulkBusyReason}
                                tooltip="Update the definition from the source insight"
                                onClick={() => refreshMetricFromInsight(metric.name)}
                                data-attr="data-catalog-review-queue-refresh"
                            >
                                Refresh
                            </LemonButton>
                        )
                    ) : (
                        <LemonButton
                            type="primary"
                            size="small"
                            loading={inFlight}
                            disabledReason={bulkBusyReason}
                            onClick={() => approveMetric(metric.name)}
                            data-attr="data-catalog-review-queue-approve"
                        >
                            Approve
                        </LemonButton>
                    )}
                    <More
                        overlay={
                            <LemonButton
                                fullWidth
                                status="danger"
                                disabledReason={bulkBusyReason ?? (inFlight ? 'Working' : undefined)}
                                onClick={() => confirmDelete(metric)}
                            >
                                Delete
                            </LemonButton>
                        }
                    />
                </div>
            )
        },
    }

    const columns = [...baseColumns, menuColumn]
    const reviewColumns = [...baseColumns, reviewActionsColumn]
    const approvedColumns = [...baseColumns.filter((column) => column.key !== 'status'), menuColumn]

    const bulkSelection = (
        barPortalTarget: HTMLDivElement | null,
        withApprove: boolean
    ): BulkSelectionConfig<DataCatalogMetricApi> => ({
        // Key on the stable id, not the name: a name is freed for reuse when a metric is
        // deleted or renamed, so a name-keyed selection could target a different metric
        // that later takes the same name.
        getKey: (metric: DataCatalogMetricApi) => metric.id,
        noun: ['metric', 'metrics'],
        rowAriaLabel: (metric: DataCatalogMetricApi) => `Select metric ${metric.name}`,
        headerAriaLabel: 'Select all metrics on this page',
        barPortalTarget,
        renderActions: (ctx) => {
            // Selection spans pages, so resolve the keys against every metric rather
            // than ctx.selectedRecords, which only covers the page on screen. Resolving
            // by id also drops any selected metric that has since left the list.
            const selected = new Set(ctx.selectedKeys)
            const selectedMetrics = allMetrics.filter((metric) => selected.has(metric.id))
            const approvableNames = selectedMetrics.filter(isApprovable).map((metric) => metric.name)
            const selectedNames = selectedMetrics.map((metric) => metric.name)
            return (
                <>
                    {withApprove && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="data-catalog-metrics-bulk-approve"
                            loading={bulkActionInFlight === 'approve'}
                            disabledReason={bulkApproveDisabledReason(approvableNames.length)}
                            onClick={() => bulkApproveMetrics(approvableNames, ctx.clearSelection)}
                        >
                            Approve ({approvableNames.length})
                        </LemonButton>
                    )}
                    <MemberSelect
                        value={null}
                        defaultLabel="Unassigned"
                        onChange={(user) =>
                            bulkChangeMetricOwner(selectedNames, user?.email ?? null, ctx.clearSelection)
                        }
                    >
                        {() => (
                            <LemonButton
                                type="secondary"
                                size="small"
                                data-attr="data-catalog-metrics-bulk-change-owner"
                                loading={bulkActionInFlight === 'change_owner'}
                                disabledReason={bulkSelectionDisabledReason(selectedNames.length, 'change_owner')}
                            >
                                Change owner
                            </LemonButton>
                        )}
                    </MemberSelect>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        data-attr="data-catalog-metrics-bulk-delete"
                        loading={bulkActionInFlight === 'delete'}
                        disabledReason={bulkSelectionDisabledReason(selectedNames.length, 'delete')}
                        onClick={() => confirmBulkDelete(selectedNames, ctx.clearSelection)}
                    >
                        Delete
                    </LemonButton>
                </>
            )
        },
    })

    return (
        <div className="@container flex flex-col gap-4">
            <CatalogExplainer />
            {reviewQueueEnabled && (
                <LifecycleStrip counts={stageCounts} status={filters.status} onToggle={toggleStage} />
            )}
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <LemonInput
                    type="search"
                    placeholder="Search metrics"
                    value={filters.search}
                    onChange={(search) => setFilters({ search })}
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Owner:</span>
                        <LemonSelect
                            size="small"
                            value={filters.owner}
                            onChange={(owner) => setFilters({ owner })}
                            options={[
                                { value: null, label: 'Any user' },
                                ...ownerFilterOptions.map((owner) => ({ value: owner, label: owner })),
                            ]}
                            data-attr="data-catalog-metrics-owner-filter"
                        />
                    </div>
                    {!reviewQueueEnabled && (
                        <LemonSegmentedButton
                            value={filters.status}
                            onChange={(status) => setFilters({ status })}
                            options={STATUS_FILTER_OPTIONS}
                            size="small"
                        />
                    )}
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadMetrics()}
                        loading={allMetricsLoading}
                        disabledReason={reloadDisabledReason}
                        size="small"
                    >
                        Reload
                    </LemonButton>
                </div>
            </div>
            {reviewQueueEnabled ? (
                <>
                    {showReviewQueue && (
                        <section className="flex flex-col gap-2" data-attr="data-catalog-review-queue">
                            <div className="flex flex-wrap items-baseline gap-x-2">
                                <h3 className="m-0">Needs review ({reviewQueue.length})</h3>
                                <span className="text-xs text-secondary">
                                    Drifted metrics come first, then your proposals, then AI proposals by confidence.
                                </span>
                            </div>
                            <LemonTable
                                id="data-catalog-review-queue"
                                data-attr="data-catalog-review-queue-table"
                                dataSource={reviewQueue}
                                rowKey="name"
                                columns={reviewColumns}
                                loading={tableLoading}
                                pagination={{ pageSize: 20 }}
                                emptyState={metricsLoadState === 'failed' ? LOAD_FAILED : 'Nothing to review.'}
                                nouns={['metric', 'metrics']}
                                onSort={(sorting) => reportCatalogTableSorted('metrics', sorting)}
                                bulkSelection={bulkSelection(bulkBarTarget, true)}
                            />
                            <div ref={setBulkBarTarget} className={BULK_BAR_CLASS} />
                        </section>
                    )}
                    {showApproved && (
                        <section className="flex flex-col gap-2" data-attr="data-catalog-approved">
                            <h3 className="m-0">Approved ({approvedMetrics.length})</h3>
                            <LemonTable
                                id="data-catalog-approved"
                                data-attr="data-catalog-approved-table"
                                dataSource={approvedMetrics}
                                rowKey="name"
                                columns={approvedColumns}
                                loading={tableLoading}
                                pagination={{ pageSize: 20 }}
                                emptyState={metricsLoadState === 'failed' ? LOAD_FAILED : 'No approved metrics yet.'}
                                nouns={['metric', 'metrics']}
                                onSort={(sorting) => reportCatalogTableSorted('metrics', sorting)}
                                bulkSelection={bulkSelection(approvedBulkBarTarget, false)}
                            />
                            <div ref={setApprovedBulkBarTarget} className={BULK_BAR_CLASS} />
                        </section>
                    )}
                </>
            ) : (
                <>
                    <LemonTable
                        id="data-catalog-metrics"
                        data-attr="data-catalog-metrics-table"
                        dataSource={metrics}
                        rowKey="name"
                        columns={columns}
                        loading={allMetricsLoading}
                        pagination={{ pageSize: 20 }}
                        emptyState={
                            allMetrics.length === 0 ? 'No metrics defined yet.' : 'No metrics match your filters.'
                        }
                        nouns={['metric', 'metrics']}
                        onSort={(sorting) => reportCatalogTableSorted('metrics', sorting)}
                        bulkSelection={bulkSelection(bulkBarTarget, true)}
                    />
                    <div ref={setBulkBarTarget} className={BULK_BAR_CLASS} />
                </>
            )}
        </div>
    )
}
