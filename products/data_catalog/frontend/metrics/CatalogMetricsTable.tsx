import { useActions, useValues } from 'kea'
import { MouseEvent } from 'react'

import {
    Avatar,
    AvatarFallback,
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

import { CATALOG_PAGE_SIZE } from '../catalogPagination'
import { sortDirectionFor } from '../catalogSort'
import { checkGroupCounts } from '../catalogTableRows'
import { humanizeDefinitionKind, metricDisplayName } from '../common'
import { CheckGroupSummary } from '../components/CheckGroupSummary'
import { ChecksToggleButton } from '../components/ChecksToggleButton'
import { isPlainRowClick } from '../components/isPlainRowClick'
import { PageSelectionCheckbox } from '../components/PageSelectionCheckbox'
import { SortHeadProps, SortableTableHead } from '../components/SortableTableHead'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { bulkBusyReason } from '../metricActionGuards'
import { DEFAULT_METRICS_FILTERS, metricsLogic } from '../metricsLogic'
import { CatalogTablesPagination } from '../tables/CatalogTablesPagination'
import { MutedCellText } from '../tables/MutedCellText'
import { CatalogMetricRowMenu } from './CatalogMetricRowMenu'
import {
    DEFAULT_METRIC_CHECKS_FILTER,
    MetricsSortColumn,
    catalogMetricsLogic,
    metricOwnerName,
    metricUpdatedAt,
} from './catalogMetricsLogic'
import { MetricApproveButton } from './MetricApproveButton'
import { MetricChecksPanel } from './MetricChecksPanel'
import { MetricOwnerCombobox } from './MetricOwnerCombobox'

const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const EXTRA_WIDE_ONLY_CELL = 'hidden @min-[72rem]/main-content:table-cell'
const COLUMN_COUNT = 9

const STATUS_LABELS: Record<string, string> = {
    approved: 'Approved',
    proposed: 'Proposed',
}

function checksPanelId(metric: DataCatalogMetricApi): string {
    return `data-catalog-metrics-checks-${metric.id}`
}

function StatusBadges({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={metric.status === 'approved' ? 'success' : 'warning'}>
                {STATUS_LABELS[metric.status] ?? metric.status}
            </Badge>
            {metric.is_drifted && <Badge variant="destructive">Drifted</Badge>}
            {metric.status === 'proposed' && <MetricApproveButton metric={metric} />}
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
    const { ownerNameByEmail } = useValues(catalogMetricsLogic)
    const ownerName = metricOwnerName(metric, ownerNameByEmail)
    return (
        <div className="flex min-w-0 items-center gap-1">
            {ownerName && (
                <Avatar size="xs">
                    <AvatarFallback>{ownerName.charAt(0).toUpperCase()}</AvatarFallback>
                </Avatar>
            )}
            <MetricOwnerCombobox
                label={ownerName || 'Unassigned'}
                variant="default"
                loading={!!actionsInFlight[metric.name]}
                disabledReason={bulkBusyReason(bulkActionInFlight)}
                onChange={(owner) => setMetricOwner(metric.name, owner)}
                dataAttr="data-catalog-metric-owner-select"
            />
        </div>
    )
}

function NameCell({ metric, expanded }: { metric: DataCatalogMetricApi; expanded: boolean }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <Button
                variant="link"
                size="inline"
                className="self-start font-medium text-foreground"
                render={<LinkPrimitive to={urls.dataCatalogMetric(metric.name)} />}
                data-attr="data-catalog-metrics-name"
            >
                {metricDisplayName(metric)}
            </Button>
            {metric.description && (
                <Text size="xs" variant="muted" className="line-clamp-2 max-w-120">
                    {stripMarkdown(metric.description)}
                </Text>
            )}
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                <StatusBadges metric={metric} />
                <MetricChecksToggle metric={metric} expanded={expanded} />
                <OwnerCell metric={metric} />
            </div>
        </div>
    )
}

function MetricChecksToggle({ metric, expanded }: { metric: DataCatalogMetricApi; expanded: boolean }): JSX.Element {
    const { checkGroupByMetricId } = useValues(catalogMetricsLogic)
    const { toggleMetricExpanded } = useActions(catalogMetricsLogic)
    const group = checkGroupByMetricId[metric.id]
    if (!group) {
        return <MutedCellText>No checks</MutedCellText>
    }
    return (
        <ChecksToggleButton
            expanded={expanded}
            controlsId={checksPanelId(metric)}
            subjectName={metricDisplayName(metric)}
            onToggle={() => toggleMetricExpanded(metric.id)}
            dataAttr="data-catalog-metrics-expand"
        >
            <CheckGroupSummary counts={checkGroupCounts(group)} subjectKey={group.subjectKey} />
        </ChecksToggleButton>
    )
}

function NoMetrics(): JSX.Element {
    const { allMetrics } = useValues(metricsLogic)
    const { setFilters } = useActions(metricsLogic)
    const { setChecksFilter } = useActions(catalogMetricsLogic)
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
                    onClick={() => {
                        setFilters(DEFAULT_METRICS_FILTERS)
                        setChecksFilter(DEFAULT_METRIC_CHECKS_FILTER)
                    }}
                    data-attr="data-catalog-metrics-show-all"
                >
                    Show all metrics
                </Button>
            </EmptyContent>
        </Empty>
    )
}

function MetricRows({
    metric,
    expanded,
    selected,
}: {
    metric: DataCatalogMetricApi
    expanded: boolean
    selected: boolean
}): JSX.Element {
    const { checkGroupByMetricId } = useValues(catalogMetricsLogic)
    const { toggleMetricExpanded, toggleMetricSelected } = useActions(catalogMetricsLogic)
    const group = checkGroupByMetricId[metric.id]
    const expandUnlessInteractive = (event: MouseEvent<HTMLTableRowElement>): void => {
        if (group && isPlainRowClick(event)) {
            toggleMetricExpanded(metric.id)
        }
    }
    return (
        <>
            <TableRow
                className={cn(group && 'cursor-pointer')}
                data-state={selected ? 'selected' : undefined}
                onClick={expandUnlessInteractive}
                data-attr="data-catalog-metrics-row"
            >
                <TableCell valign="top" className="w-0 pr-0">
                    <Checkbox
                        aria-label={`Select metric ${metric.name}`}
                        checked={selected}
                        onCheckedChange={() => toggleMetricSelected(metric.id)}
                        data-attr="data-catalog-metrics-select"
                    />
                </TableCell>
                <TableCell expand valign="top">
                    <NameCell metric={metric} expanded={expanded} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <StatusBadges metric={metric} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <MetricChecksToggle metric={metric} expanded={expanded} />
                </TableCell>
                <TableCell valign="top" className={EXTRA_WIDE_ONLY_CELL}>
                    <Badge>{humanizeDefinitionKind(metric.definition_kind)}</Badge>
                </TableCell>
                <TableCell valign="top" className={EXTRA_WIDE_ONLY_CELL}>
                    <SourceBadge metric={metric} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <OwnerCell metric={metric} />
                </TableCell>
                <TableCell valign="top" className={cn(WIDE_ONLY_CELL, 'whitespace-nowrap')}>
                    <Text size="xs" variant="muted">
                        <TZLabel time={metricUpdatedAt(metric)} />
                    </Text>
                </TableCell>
                <TableCell valign="top" align="right" className="w-0">
                    <CatalogMetricRowMenu metric={metric} />
                </TableCell>
            </TableRow>
            {expanded && group && (
                <TableRow id={checksPanelId(metric)}>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <MetricChecksPanel metric={metric} group={group} />
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

export function CatalogMetricsTable(): JSX.Element {
    const {
        visibleMetrics,
        pageMetrics: pageItems,
        currentPage,
        pageCount,
        sort,
        selectedMetricIds,
        expandedMetricIds,
    } = useValues(catalogMetricsLogic)
    const { toggleSort, setPage, setMetricsSelected } = useActions(catalogMetricsLogic)
    const sortProps = (column: MetricsSortColumn): SortHeadProps => ({
        direction: sortDirectionFor(sort, column),
        onToggle: () => toggleSort(column),
        dataAttr: `data-catalog-metrics-sort-${column}`,
    })
    const pageIds = pageItems.map((metric) => metric.id)

    return (
        <div data-attr="data-catalog-metrics-table">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-0 pr-0">
                            <PageSelectionCheckbox
                                label="Select all metrics on this page"
                                pageIds={pageIds}
                                selectedIds={selectedMetricIds}
                                onChange={setMetricsSelected}
                            />
                        </TableHead>
                        <SortableTableHead label="Name" expand {...sortProps('name')} />
                        <SortableTableHead label="Status" className={WIDE_ONLY_CELL} {...sortProps('status')} />
                        <SortableTableHead label="Checks" className={WIDE_ONLY_CELL} {...sortProps('checks')} />
                        <TableHead className={EXTRA_WIDE_ONLY_CELL}>Definition</TableHead>
                        <TableHead className={EXTRA_WIDE_ONLY_CELL}>Source</TableHead>
                        <SortableTableHead label="Owner" className={WIDE_ONLY_CELL} {...sortProps('owner')} />
                        <SortableTableHead label="Last updated" className={WIDE_ONLY_CELL} {...sortProps('updated')} />
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
                            <MetricRows
                                key={metric.id}
                                metric={metric}
                                expanded={expandedMetricIds.includes(metric.id)}
                                selected={selectedMetricIds.includes(metric.id)}
                            />
                        ))}
                    </TableBody>
                )}
            </Table>
            {pageCount > 1 && (
                <CatalogTablesPagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={CATALOG_PAGE_SIZE}
                    total={visibleMetrics.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
