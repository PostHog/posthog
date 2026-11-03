import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Button, DataTable, type DataTableProps, Heading, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { nodeEndpointModel } from './endpointModelName'
import { ModelsOverviewAttentionFilter } from './ModelsOverviewAttentionFilter'
import { ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'
import { ModelsOverviewErrorCallout } from './ModelsOverviewErrorCallout'
import { AttentionSubject, modelsOverviewLogic } from './modelsOverviewLogic'
import { ModelsOverviewNextStep } from './ModelsOverviewNextStep'
import { ModelsOverviewProblemBadges } from './ModelsOverviewProblemBadges'
import { subjectDetail, subjectImpact, subjectName, subjectSince } from './overviewIssueCopy'
import { subjectHref } from './subjectHref'
import { useHoldTallestHeight } from './useHoldTallestHeight'

const WIDE_ONLY = 'hidden @min-[40rem]/main-content:inline'
const WIDE_ONLY_BLOCK = 'hidden @min-[40rem]/main-content:block'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const SKELETON_ROWS = 3
const PAGE_SIZE = 10
const SECTION_ID = 'models-overview-attention-section'
const HEADING_ID = `${SECTION_ID}-heading`
const DESCRIPTION_ID = `${SECTION_ID}-description`

interface SubjectCellContext {
    row: { original: AttentionSubject }
}

function subjectLabel(subject: AttentionSubject): string {
    const endpointModel = subject.node ? nodeEndpointModel(subject.node) : null
    return endpointModel ? `${endpointModel.endpointName} v${endpointModel.version}` : subjectName(subject)
}

function NameLink({ subject }: { subject: AttentionSubject }): JSX.Element {
    const href = subjectHref(subject)
    const label = subjectLabel(subject)
    if (!href) {
        return <Text size="xs">{label}</Text>
    }
    return (
        <Button
            variant="link"
            size="inline"
            className="self-start font-medium text-foreground"
            render={<LinkPrimitive to={href} />}
        >
            {label}
        </Button>
    )
}

function DetailText({ subject }: { subject: AttentionSubject }): JSX.Element {
    const detail = subjectDetail(subject)
    const impact = subjectImpact(subject)
    return (
        <div className="flex min-w-0 flex-col">
            {detail && (
                <Text size="xs" variant="muted" className="line-clamp-1" title={detail}>
                    {detail}
                </Text>
            )}
            {impact && (
                <Text size="xs" variant="muted" className="line-clamp-1">
                    {impact}
                </Text>
            )}
        </div>
    )
}

function SinceText({ subject }: { subject: AttentionSubject }): JSX.Element | null {
    const since = subjectSince(subject)
    if (!since) {
        return null
    }
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {since.kind === 'time' ? <TZLabel time={since.time} /> : since.label}
        </Text>
    )
}

function NarrowLines({ subject }: { subject: AttentionSubject }): JSX.Element {
    return (
        <div className={`${NARROW_ONLY} flex flex-col gap-1`}>
            <ModelsOverviewProblemBadges subject={subject} />
            <DetailText subject={subject} />
            <SinceText subject={subject} />
            <div className="pt-1">
                <ModelsOverviewNextStep subject={subject} />
            </div>
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
                <ModelsOverviewProblemBadges subject={row.original} />
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
        id: 'since',
        header: () => <span className={WIDE_ONLY}>Since</span>,
        enableSorting: false,
        cell: ({ row }: SubjectCellContext) => (
            <span className={WIDE_ONLY}>
                <SinceText subject={row.original} />
            </span>
        ),
    },
    {
        id: 'next-step',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: SubjectCellContext) => (
            <span className={WIDE_ONLY}>
                <ModelsOverviewNextStep subject={row.original} />
            </span>
        ),
    },
]

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
        filteredAttentionSubjects,
        nothingToReport,
        modelsFailed,
        overviewError,
        checksStatus,
        checksTruncated,
        modelsFirstLoading,
        checksFirstLoading,
        refreshSummary,
        catalogRestructureEnabled,
    } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)

    if (nothingToReport) {
        return (
            <ModelsOverviewEmptyState
                variant="healthy"
                checksStatus={checksStatus}
                checksTruncated={checksTruncated}
                refreshSummary={refreshSummary}
            />
        )
    }

    const loading = (modelsFirstLoading || checksFirstLoading) && attentionSubjects.length === 0

    return (
        <section
            id={SECTION_ID}
            aria-labelledby={HEADING_ID}
            aria-describedby={DESCRIPTION_ID}
            className="flex flex-col gap-2"
        >
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                    <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                        <span>Views and tables that need attention</span>
                        {attentionSubjects.length > 0 && (
                            <span translate="no" className="ml-2 font-normal text-muted-foreground">
                                {attentionSubjects.length}
                            </span>
                        )}
                    </Heading>
                    {!catalogRestructureEnabled && (
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
                    )}
                </div>
                <Text size="xs" variant="muted" render={<p id={DESCRIPTION_ID} className="m-0" />}>
                    These failed to refresh or have failing checks, so anything that reads them may show stale or wrong
                    data.
                </Text>
            </div>
            <ModelsOverviewAttentionFilter />
            {modelsFailed && (
                <ModelsOverviewErrorCallout
                    message="Your models could not be loaded, so this page cannot say which ones need attention."
                    onRetry={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    dataAttr="models-overview-models-error"
                />
            )}
            {overviewError && (
                <ModelsOverviewErrorCallout
                    message="Data quality checks could not be loaded, so this page cannot say whether any are failing."
                    onRetry={() => loadOverview()}
                    dataAttr="models-overview-checks-error"
                />
            )}
            {loading &&
                Array.from({ length: SKELETON_ROWS }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
            {filteredAttentionSubjects.length > 0 && <SubjectTable subjects={filteredAttentionSubjects} />}
        </section>
    )
}
