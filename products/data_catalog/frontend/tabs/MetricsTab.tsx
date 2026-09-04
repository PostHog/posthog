import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { METRIC_BULK_MAX, humanizeDefinitionKind, metricCount } from '../common'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { BulkMetricAction, MetricStatusFilter, metricsLogic } from '../metricsLogic'

const STATUS_FILTER_OPTIONS: { value: MetricStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'approved', label: 'Approved' },
]

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
    const { metrics, allMetrics, allMetricsLoading, filters, actionsInFlight, bulkActionInFlight } =
        useValues(metricsLogic)
    const {
        setFilters,
        loadMetrics,
        approveMetric,
        refreshMetricFromInsight,
        deleteMetric,
        openNewMetricModal,
        bulkApproveMetrics,
        bulkDeleteMetrics,
    } = useActions(metricsLogic)

    const bulkBusyReason = bulkActionInFlight ? 'A bulk action is running' : undefined
    // Reload replaces the whole list and takes no breakpoint, so a load that resolves after a
    // mutation would repaint pre-mutation rows (e.g. bring back rows a bulk delete just removed).
    // Block it while any mutation is in flight; the view is authoritative again on the next load.
    const reloadDisabledReason =
        bulkBusyReason ?? (Object.values(actionsInFlight).some(Boolean) ? 'A metric action is running' : undefined)
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

    if (!allMetricsLoading && allMetrics.length === 0) {
        return (
            <ProductIntroduction
                productName="Data catalog"
                productKey={ProductKey.DATA_CATALOG}
                thingName="metric"
                description="Metrics give your team one canonical definition for a number. Define one from SQL, an insight, or written instructions."
                isEmpty
                action={openNewMetricModal}
            />
        )
    }

    const columns: LemonTableColumns<DataCatalogMetricApi> = [
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
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, metric) => <StatusTag metric={metric} />,
        },
        {
            title: 'Definition',
            key: 'definition_kind',
            render: (_, metric) => <LemonTag type="option">{humanizeDefinitionKind(metric.definition_kind)}</LemonTag>,
        },
        {
            title: 'Source',
            key: 'created_source',
            render: (_, metric) => <SourceTag metric={metric} />,
        },
        {
            title: 'Owner',
            key: 'owner',
            render: (_, metric) => metric.owner || <span className="text-secondary">Unassigned</span>,
        },
        createdAtColumn<DataCatalogMetricApi>() as LemonTableColumns<DataCatalogMetricApi>[number],
        {
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
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <LemonInput
                    type="search"
                    placeholder="Search metrics"
                    value={filters.search}
                    onChange={(search) => setFilters({ search })}
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSegmentedButton
                        value={filters.status}
                        onChange={(status) => setFilters({ status })}
                        options={STATUS_FILTER_OPTIONS}
                        size="small"
                    />
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
            <LemonTable
                data-attr="data-catalog-metrics-table"
                dataSource={metrics}
                rowKey="name"
                columns={columns}
                loading={allMetricsLoading}
                pagination={{ pageSize: 20 }}
                emptyState="No metrics match your filters."
                nouns={['metric', 'metrics']}
                bulkSelection={{
                    // Key on the stable id, not the name: a name is freed for reuse when a metric is
                    // deleted or renamed, so a name-keyed selection could target a different metric
                    // that later takes the same name.
                    getKey: (metric: DataCatalogMetricApi) => metric.id,
                    noun: ['metric', 'metrics'],
                    rowAriaLabel: (metric: DataCatalogMetricApi) => `Select metric ${metric.name}`,
                    headerAriaLabel: 'Select all metrics on this page',
                    barPortalTarget: bulkBarTarget,
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
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    size="small"
                                    data-attr="data-catalog-metrics-bulk-delete"
                                    loading={bulkActionInFlight === 'delete'}
                                    disabledReason={
                                        selectedNames.length === 0
                                            ? 'The selected metrics are no longer available. Reload the list.'
                                            : selectedNames.length > METRIC_BULK_MAX
                                              ? OVER_CAP_REASON
                                              : otherBulkActionReason('delete')
                                    }
                                    onClick={() => confirmBulkDelete(selectedNames, ctx.clearSelection)}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        )
                    },
                }}
            />
            <div
                ref={setBulkBarTarget}
                className="sticky bottom-4 z-10 self-center w-fit rounded border border-primary bg-surface-primary px-2 py-1 shadow empty:hidden"
            />
        </div>
    )
}
