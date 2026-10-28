import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import {
    Badge,
    Button,
    DataTable,
    type DataTableProps,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import { checkDisplayName, failingForLabel } from 'products/data_quality/frontend/checksConstants'
import { subjectDetailUrl } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { nodeEndpointModel, nodeEndpointUrl } from './endpointModelName'
import { healthyMessage } from './healthyMessage'
import { modelsOverviewLogic, OverviewIssue } from './modelsOverviewLogic'
import { downstreamSummary, IssueTone, issueDetail, issueStatus } from './overviewIssueCopy'

const WIDE_ONLY = 'hidden @min-[40rem]/main-content:inline'
const WIDE_ONLY_BLOCK = 'hidden @min-[40rem]/main-content:block'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const SKELETON_ROWS = 3

interface IssueCellContext {
    row: { original: OverviewIssue }
}

const BADGE_VARIANTS: Record<IssueTone, 'destructive' | 'warning'> = {
    danger: 'destructive',
    warning: 'warning',
}

function issueNode(issue: Exclude<OverviewIssue, { kind: 'check' }>): DataModelingNode {
    return issue.kind === 'behind' ? issue.behind.node : issue.attention.node
}

function nameTarget(issue: OverviewIssue): { href: string | null; name: string } {
    if (issue.kind === 'check') {
        return { href: subjectDetailUrl(issue.check), name: checkDisplayName(issue.check) }
    }
    const node = issueNode(issue)
    const endpointModel = nodeEndpointModel(node)
    return endpointModel
        ? { href: nodeEndpointUrl(node), name: `${endpointModel.endpointName} v${endpointModel.version}` }
        : { href: urls.nodeDetail(node.id), name: node.name }
}

function StatusBadge({ issue }: { issue: OverviewIssue }): JSX.Element {
    const { label, tone, tooltip } = issueStatus(issue)
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                <Badge variant={BADGE_VARIANTS[tone]}>{label}</Badge>
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function NameLink({ issue }: { issue: OverviewIssue }): JSX.Element {
    const target = nameTarget(issue)
    if (!target.href) {
        return <Text size="xs">{target.name}</Text>
    }
    return (
        <Button variant="link" size="inline" className="self-start" render={<LinkPrimitive to={target.href} />}>
            {target.name}
        </Button>
    )
}

function DetailText({ issue }: { issue: OverviewIssue }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="line-clamp-1" title={issueDetail(issue) ?? undefined}>
            {issueDetail(issue) ?? '-'}
        </Text>
    )
}

function FactText({ issue }: { issue: OverviewIssue }): JSX.Element {
    if (issue.kind === 'check') {
        return (
            <Text size="xs" variant="muted" className="whitespace-nowrap">
                {failingForLabel(issue.check) ?? issue.check.last_status}
            </Text>
        )
    }
    if (issue.kind === 'behind') {
        const lastRunAt = issue.behind.node.last_run_at
        return (
            <Text size="xs" variant="muted" className="whitespace-nowrap">
                {lastRunAt ? (
                    <>
                        <span>Last refreshed </span>
                        <TZLabel time={lastRunAt} />
                    </>
                ) : (
                    'Never refreshed'
                )}
            </Text>
        )
    }
    const { holdsUp, skipped } = downstreamSummary(issue.attention)
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {[holdsUp ?? 'Nothing downstream', skipped].filter(Boolean).join(', ')}
        </Text>
    )
}

const COLUMNS: DataTableProps<OverviewIssue, unknown>['columns'] = [
    {
        id: 'status',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }: IssueCellContext) => <StatusBadge issue={row.original} />,
    },
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }: IssueCellContext) => (
            <div className="flex min-w-0 flex-col gap-0.5">
                <NameLink issue={row.original} />
                <div className={NARROW_ONLY}>
                    <DetailText issue={row.original} />
                    <FactText issue={row.original} />
                </div>
            </div>
        ),
    },
    {
        id: 'detail',
        header: () => <span className={WIDE_ONLY}>Detail</span>,
        enableSorting: false,
        cell: ({ row }: IssueCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} min-w-48 max-w-96`}>
                <DetailText issue={row.original} />
            </span>
        ),
    },
    {
        id: 'fact',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: IssueCellContext) => (
            <span className={WIDE_ONLY}>
                <FactText issue={row.original} />
            </span>
        ),
    },
]

function ErrorCallout({
    message,
    onRetry,
    dataAttr,
}: {
    message: string
    onRetry: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <Item variant="outline" tone="destructive" data-attr={dataAttr}>
            <ItemContent>
                <ItemDescription>{message}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onRetry}>
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}

interface IssueSectionProps {
    id: string
    title: string
    issues: OverviewIssue[]
    loading: boolean
    allLink: { to: string; label: string; dataAttr: string }
    error: ReactNode
    tableDataAttr: string
}

function IssueSection({ id, title, issues, loading, allLink, error, tableDataAttr }: IssueSectionProps): JSX.Element {
    const headingId = `${id}-heading`
    return (
        <section id={id} aria-labelledby={headingId} className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
                <Heading size="base" render={<h3 id={headingId} className="m-0" />}>
                    <span>{title}</span>
                    {issues.length > 0 && (
                        <span translate="no" className="ml-2 font-normal text-muted-foreground">
                            {issues.length}
                        </span>
                    )}
                </Heading>
                <Button variant="link" render={<LinkPrimitive to={allLink.to} />} data-attr={allLink.dataAttr}>
                    {allLink.label}
                </Button>
            </div>
            {error}
            {loading &&
                Array.from({ length: SKELETON_ROWS }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
            {issues.length > 0 && (
                <div data-attr={tableDataAttr}>
                    <DataTable columns={COLUMNS} data={issues} pageSize={10} size="sm" fullWidth />
                </div>
            )}
        </section>
    )
}

export function ModelsOverviewIssues(): JSX.Element {
    const {
        materializationIssues,
        checkIssues,
        nothingToReport,
        modelsFailed,
        overviewError,
        checksStatus,
        checksTruncated,
        modelsFirstLoading,
        checksFirstLoading,
    } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)

    return (
        <>
            {(modelsFirstLoading || modelsFailed || materializationIssues.length > 0) && (
                <IssueSection
                    id="models-overview-materialization"
                    title="Materialization"
                    issues={materializationIssues}
                    loading={modelsFirstLoading}
                    allLink={{ to: urls.models('models'), label: 'All models', dataAttr: 'models-overview-all-models' }}
                    tableDataAttr="models-overview-attention"
                    error={
                        modelsFailed && (
                            <ErrorCallout
                                message="Your models could not be loaded, so this page cannot say which ones need attention."
                                onRetry={() => {
                                    loadNodes()
                                    loadDataWarehouseSavedQueries()
                                }}
                                dataAttr="models-overview-models-error"
                            />
                        )
                    }
                />
            )}
            {(checksFirstLoading || overviewError || checkIssues.length > 0) && (
                <IssueSection
                    id="models-overview-data-quality"
                    title="Data quality"
                    issues={checkIssues}
                    loading={checksFirstLoading}
                    allLink={{
                        to: urls.models('data-quality'),
                        label: 'All checks',
                        dataAttr: 'models-overview-all-checks',
                    }}
                    tableDataAttr="models-overview-failing-checks"
                    error={
                        overviewError && (
                            <ErrorCallout
                                message="Data quality checks could not be loaded, so this page cannot say whether any are failing."
                                onRetry={() => loadOverview()}
                                dataAttr="models-overview-checks-error"
                            />
                        )
                    }
                />
            )}
            {nothingToReport && (
                <Text size="xs" variant="muted" render={<p className="m-0" data-attr="models-overview-healthy" />}>
                    <span>{healthyMessage(checksStatus, checksTruncated)}</span>
                    {checksStatus === 'none' && (
                        <Button
                            variant="link"
                            size="inline"
                            className="ml-1"
                            render={<LinkPrimitive to={urls.models('data-quality')} />}
                            data-attr="models-overview-checks"
                        >
                            Set up checks
                        </Button>
                    )}
                </Text>
            )}
        </>
    )
}
