import { useActions, useValues } from 'kea'

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

import { humanizeDefinitionKind } from '../common'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricStatusFilter, metricsLogic } from '../metricsLogic'

const STATUS_FILTER_OPTIONS: { value: MetricStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'approved', label: 'Approved' },
]

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
    const { metrics, allMetrics, allMetricsLoading, filters, actionsInFlight } = useValues(metricsLogic)
    const { setFilters, loadMetrics, approveMetric, refreshMetricFromInsight, deleteMetric, openNewMetricModal } =
        useActions(metricsLogic)

    const confirmDelete = (metric: DataCatalogMetricApi): void => {
        LemonDialog.open({
            title: 'Delete metric?',
            content: <div className="text-sm text-secondary">Deleting {metric.name} cannot be undone.</div>,
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => deleteMetric(metric.name),
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
                                            metric.is_drifted
                                                ? 'This metric has drifted from its source insight. Refresh it first.'
                                                : undefined
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
                                        onClick={() => refreshMetricFromInsight(metric.name)}
                                    >
                                        Refresh from insight
                                    </LemonButton>
                                )}
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    disabledReason={inFlight ? 'Working' : undefined}
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
            />
        </div>
    )
}
