import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Checkbox,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { stripMarkdown } from 'lib/utils/markdown'
import { urls } from 'scenes/urls'

import { humanizeDefinitionKind } from '../common'
import { usePagedItems } from '../components/usePagedItems'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { bulkBusyReason } from '../metricActionGuards'
import { DEFAULT_METRICS_FILTERS, metricsLogic } from '../metricsLogic'
import { CatalogTablesPagination } from '../tables/CatalogTablesPagination'
import { CatalogMetricRowMenu } from './CatalogMetricRowMenu'
import { MetricOwnerCombobox } from './MetricOwnerCombobox'

const METRICS_PAGE_SIZE = 20
const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'

const STATUS_LABELS: Record<string, string> = {
    approved: 'Approved',
    proposed: 'Proposed',
}

interface MetricSelectionProps {
    selectedIds: string[]
    setSelectedIds: (ids: string[]) => void
}

function StatusBadges({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={metric.status === 'approved' ? 'success' : 'warning'}>
                {STATUS_LABELS[metric.status] ?? metric.status}
            </Badge>
            {metric.is_drifted && <Badge variant="destructive">Drifted</Badge>}
        </div>
    )
}

function SourceBadge({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    if (metric.created_source !== 'ai_generated') {
        return (
            <Text size="xs" variant="muted">
                User
            </Text>
        )
    }
    const confidencePercent = metric.confidence != null ? `${Math.round(metric.confidence * 100)}%` : 'unknown'
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>
                <Badge variant="info">AI</Badge>
            </TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-1">
                    <span>Confidence: {confidencePercent}</span>
                    {metric.ai_model && <span>Model: {metric.ai_model}</span>}
                    {metric.reasoning && <span>{metric.reasoning}</span>}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

function OwnerCell({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    const { actionsInFlight, bulkActionInFlight } = useValues(metricsLogic)
    const { setMetricOwner } = useActions(metricsLogic)
    return (
        <MetricOwnerCombobox
            label={metric.owner || 'Unassigned'}
            variant="default"
            loading={!!actionsInFlight[metric.name]}
            disabledReason={bulkBusyReason(bulkActionInFlight)}
            onChange={(owner) => setMetricOwner(metric.name, owner)}
            dataAttr="data-catalog-metric-owner-select"
        />
    )
}

function NameCell({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <Button
                variant="link"
                size="inline"
                className="self-start font-medium text-foreground"
                render={<LinkPrimitive to={urls.dataCatalogMetric(metric.name)} />}
                data-attr="data-catalog-metrics-name"
            >
                {metric.display_name || metric.name}
            </Button>
            {metric.description && (
                <Text size="xs" variant="muted" className="line-clamp-2 max-w-120">
                    {stripMarkdown(metric.description)}
                </Text>
            )}
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                <StatusBadges metric={metric} />
                <OwnerCell metric={metric} />
            </div>
        </div>
    )
}

function NoMetrics(): JSX.Element {
    const { allMetrics } = useValues(metricsLogic)
    const { setFilters } = useActions(metricsLogic)
    if (allMetrics.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>No metrics yet</EmptyTitle>
                    <EmptyDescription>Create a metric to define a number your team can reuse.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No metrics match</EmptyTitle>
                <EmptyDescription>Change the search or the filters to see more metrics.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setFilters(DEFAULT_METRICS_FILTERS)}
                    data-attr="data-catalog-metrics-show-all"
                >
                    Show all metrics
                </Button>
            </EmptyContent>
        </Empty>
    )
}

function PageSelectionCheckbox({
    pageIds,
    selectedIds,
    setSelectedIds,
}: MetricSelectionProps & { pageIds: string[] }): JSX.Element {
    const selectedOnPage = pageIds.filter((id) => selectedIds.includes(id)).length
    const allSelected = pageIds.length > 0 && selectedOnPage === pageIds.length
    return (
        <Checkbox
            aria-label="Select all metrics on this page"
            checked={allSelected}
            indeterminate={selectedOnPage > 0 && !allSelected}
            disabled={pageIds.length === 0}
            onCheckedChange={(checked: boolean) =>
                setSelectedIds(
                    checked
                        ? [...new Set([...selectedIds, ...pageIds])]
                        : selectedIds.filter((id) => !pageIds.includes(id))
                )
            }
        />
    )
}

function MetricRow({
    metric,
    selectedIds,
    setSelectedIds,
}: MetricSelectionProps & { metric: DataCatalogMetricApi }): JSX.Element {
    const selected = selectedIds.includes(metric.id)
    return (
        <TableRow data-state={selected ? 'selected' : undefined} data-attr="data-catalog-metrics-row">
            <TableCell valign="top" className="w-0 pr-0">
                <Checkbox
                    aria-label={`Select metric ${metric.name}`}
                    checked={selected}
                    onCheckedChange={(checked: boolean) =>
                        setSelectedIds(
                            checked ? [...selectedIds, metric.id] : selectedIds.filter((id) => id !== metric.id)
                        )
                    }
                />
            </TableCell>
            <TableCell expand valign="top">
                <NameCell metric={metric} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <StatusBadges metric={metric} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <Badge>{humanizeDefinitionKind(metric.definition_kind)}</Badge>
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <SourceBadge metric={metric} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <OwnerCell metric={metric} />
            </TableCell>
            <TableCell valign="top" className={cn(WIDE_ONLY_CELL, 'whitespace-nowrap')}>
                <Text size="xs" variant="muted">
                    <TZLabel time={metric.created_at} />
                </Text>
            </TableCell>
            <TableCell valign="top" align="right" className="w-0">
                <CatalogMetricRowMenu metric={metric} />
            </TableCell>
        </TableRow>
    )
}

export function CatalogMetricsTable({ selectedIds, setSelectedIds }: MetricSelectionProps): JSX.Element {
    const { metrics } = useValues(metricsLogic)
    const { pageItems, currentPage, pageCount, setPage } = usePagedItems(metrics, METRICS_PAGE_SIZE)
    const pageIds = pageItems.map((metric) => metric.id)

    return (
        <div data-attr="data-catalog-metrics-table">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-0 pr-0">
                            <PageSelectionCheckbox
                                pageIds={pageIds}
                                selectedIds={selectedIds}
                                setSelectedIds={setSelectedIds}
                            />
                        </TableHead>
                        <TableHead expand>Name</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Status</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Definition</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Source</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Owner</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Created</TableHead>
                        <TableHead className="w-0">
                            <span className="sr-only">Actions</span>
                        </TableHead>
                    </TableRow>
                </TableHeader>
                {pageItems.length === 0 ? (
                    <TableEmpty>
                        <NoMetrics />
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {pageItems.map((metric) => (
                            <MetricRow
                                key={metric.id}
                                metric={metric}
                                selectedIds={selectedIds}
                                setSelectedIds={setSelectedIds}
                            />
                        ))}
                    </TableBody>
                )}
            </Table>
            {pageCount > 1 && (
                <CatalogTablesPagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={METRICS_PAGE_SIZE}
                    total={metrics.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
