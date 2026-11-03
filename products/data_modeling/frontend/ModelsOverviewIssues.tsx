import { useActions, useValues } from 'kea'
import { useRef } from 'react'

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

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { subjectDetailUrl } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { nodeEndpointModel, nodeEndpointUrl } from './endpointModelName'
import { ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'
import { AttentionSubject, modelsOverviewLogic } from './modelsOverviewLogic'
import {
    IssueStatus,
    IssueTone,
    failingChecksStatus,
    materializationStatus,
    subjectDetail,
    subjectImpact,
    subjectName,
} from './overviewIssueCopy'
import { useHoldTallestHeight } from './useHoldTallestHeight'

const WIDE_ONLY = 'hidden @min-[40rem]/main-content:inline'
const WIDE_ONLY_BLOCK = 'hidden @min-[40rem]/main-content:block'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const SKELETON_ROWS = 3
const PAGE_SIZE = 10
const SECTION_ID = 'models-overview-attention-section'
const HEADING_ID = `${SECTION_ID}-heading`

interface SubjectCellContext {
    row: { original: AttentionSubject }
}

const BADGE_VARIANTS: Record<IssueTone, 'destructive' | 'warning'> = {
    danger: 'destructive',
    warning: 'warning',
}

function subjectHref(subject: AttentionSubject): string | null {
    if (subject.node) {
        return nodeEndpointModel(subject.node) ? nodeEndpointUrl(subject.node) : urls.nodeDetail(subject.node.id)
    }
    const [check] = subject.failingChecks
    return check ? subjectDetailUrl(check) : null
}

function subjectLabel(subject: AttentionSubject): string {
    const endpointModel = subject.node ? nodeEndpointModel(subject.node) : null
    return endpointModel ? `${endpointModel.endpointName} v${endpointModel.version}` : subjectName(subject)
}

function subjectStatuses(subject: AttentionSubject): IssueStatus[] {
    return [
        ...(subject.materialization ? [materializationStatus(subject.materialization)] : []),
        ...(subject.failingChecks.length > 0 ? [failingChecksStatus(subject.failingChecks)] : []),
    ]
}

function ProblemBadges({ subject }: { subject: AttentionSubject }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {subjectStatuses(subject).map(({ label, tone, tooltip }) => (
                <Tooltip key={label}>
                    <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                        <Badge variant={BADGE_VARIANTS[tone]}>{label}</Badge>
                    </TooltipTrigger>
                    <TooltipContent>{tooltip}</TooltipContent>
                </Tooltip>
            ))}
        </div>
    )
}

function NameLink({ subject }: { subject: AttentionSubject }): JSX.Element {
    const href = subjectHref(subject)
    const label = subjectLabel(subject)
    if (!href) {
        return <Text size="xs">{label}</Text>
    }
    return (
        <Button variant="link" size="inline" className="self-start" render={<LinkPrimitive to={href} />}>
            {label}
        </Button>
    )
}

function DetailText({ subject }: { subject: AttentionSubject }): JSX.Element {
    const detail = subjectDetail(subject)
    return (
        <Text size="xs" variant="muted" className="line-clamp-1" title={detail ?? undefined}>
            {detail ?? '-'}
        </Text>
    )
}

function ImpactText({ impact }: { impact: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {impact}
        </Text>
    )
}

function NarrowLines({ subject }: { subject: AttentionSubject }): JSX.Element {
    const impact = subjectImpact(subject)
    return (
        <div className={`${NARROW_ONLY} flex flex-col gap-1`}>
            <ProblemBadges subject={subject} />
            <DetailText subject={subject} />
            {impact && <ImpactText impact={impact} />}
        </div>
    )
}

const COLUMNS: DataTableProps<AttentionSubject, unknown>['columns'] = [
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }: SubjectCellContext) => (
            <div className="flex min-w-0 flex-col gap-1">
                <NameLink subject={row.original} />
                <NarrowLines subject={row.original} />
            </div>
        ),
    },
    {
        id: 'problems',
        header: () => <span className={WIDE_ONLY}>Problems</span>,
        enableSorting: false,
        cell: ({ row }: SubjectCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} w-max`}>
                <ProblemBadges subject={row.original} />
            </span>
        ),
    },
    {
        id: 'detail',
        header: () => <span className={WIDE_ONLY}>Detail</span>,
        enableSorting: false,
        cell: ({ row }: SubjectCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} min-w-48 max-w-96`}>
                <DetailText subject={row.original} />
            </span>
        ),
    },
    {
        id: 'impact',
        header: () => <span className={WIDE_ONLY}>Impact</span>,
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: SubjectCellContext) => (
            <span className={WIDE_ONLY}>
                <ImpactText impact={subjectImpact(row.original) ?? '-'} />
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

function SubjectTable({ subjects }: { subjects: AttentionSubject[] }): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    useHoldTallestHeight(containerRef, contentRef, subjects.length > PAGE_SIZE)

    return (
        <div ref={containerRef} data-attr="models-overview-attention">
            <div ref={contentRef}>
                <DataTable columns={COLUMNS} data={subjects} pageSize={PAGE_SIZE} size="sm" fullWidth />
            </div>
        </div>
    )
}

export function ModelsOverviewIssues(): JSX.Element {
    const {
        attentionSubjects,
        nothingToReport,
        modelsFailed,
        overviewError,
        checksStatus,
        checksTruncated,
        modelsFirstLoading,
        checksFirstLoading,
    } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)

    if (nothingToReport) {
        return (
            <ModelsOverviewEmptyState variant="healthy" checksStatus={checksStatus} checksTruncated={checksTruncated} />
        )
    }

    const loading = (modelsFirstLoading || checksFirstLoading) && attentionSubjects.length === 0

    return (
        <section id={SECTION_ID} aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                    <span>Views and tables that need attention</span>
                    {attentionSubjects.length > 0 && (
                        <span translate="no" className="ml-2 font-normal text-muted-foreground">
                            {attentionSubjects.length}
                        </span>
                    )}
                </Heading>
                <div className="flex gap-2">
                    <Button
                        variant="link"
                        render={<LinkPrimitive to={urls.models('models')} />}
                        data-attr="models-overview-all-models"
                    >
                        All models
                    </Button>
                    <Button
                        variant="link"
                        render={<LinkPrimitive to={urls.models('data-quality')} />}
                        data-attr="models-overview-all-checks"
                    >
                        All checks
                    </Button>
                </div>
            </div>
            {modelsFailed && (
                <ErrorCallout
                    message="Your models could not be loaded, so this page cannot say which ones need attention."
                    onRetry={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    dataAttr="models-overview-models-error"
                />
            )}
            {overviewError && (
                <ErrorCallout
                    message="Data quality checks could not be loaded, so this page cannot say whether any are failing."
                    onRetry={() => loadOverview()}
                    dataAttr="models-overview-checks-error"
                />
            )}
            {loading &&
                Array.from({ length: SKELETON_ROWS }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
            {attentionSubjects.length > 0 && <SubjectTable subjects={attentionSubjects} />}
        </section>
    )
}
