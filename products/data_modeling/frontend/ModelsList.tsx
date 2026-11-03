import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    DataTable,
    type DataTableProps,
    Dot,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { pluralize } from 'lib/utils/strings'
import { CADENCE_LABELS } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'
import { urls } from 'scenes/urls'

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { DataWarehouseSavedQueryOrigin } from '~/queries/schema/schema-general'
import { AccessControlResourceType, DataModelingJobStatus } from '~/types'

import { SuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsStrip'
import { WarehouseSuggestionKindEnumApi } from 'products/warehouse_suggestions/frontend/generated/api.schemas'

import { parseEndpointModelName } from './endpointModelName'
import { ModelsListHealthFilter } from './ModelsListHealthFilter'
import { ModelsListHealthyLine } from './ModelsListHealthyLine'
import { MODELS_LIST_PAGE_SIZE, ModelRow, modelsListLogic, rowNeedsAttention } from './modelsListLogic'
import { ModelsListPagination } from './ModelsListPagination'
import { ModelsListRowActions } from './ModelsListRowActions'
import { ModelsListSearch } from './ModelsListSearch'
import { ModelsOverviewErrorCallout } from './ModelsOverviewErrorCallout'
import { modelsOverviewLogic } from './modelsOverviewLogic'
import { ModelsOverviewNextStep } from './ModelsOverviewNextStep'
import { ModelsOverviewProblemBadges } from './ModelsOverviewProblemBadges'
import { subjectDetail, subjectSince } from './overviewIssueCopy'
import { modelRowHref } from './subjectHref'
import { useHoldTallestHeight } from './useHoldTallestHeight'
import { viewsTabLogic } from './viewsTabLogic'

const WIDE_ONLY = 'hidden @min-[40rem]/main-content:inline'
const WIDE_ONLY_BLOCK = 'hidden @min-[40rem]/main-content:block'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const SKELETON_ROWS = 3
const RUN_HISTORY_LENGTH = 5
const HEADING_ID = 'models-list-heading'

const RUN_DOT_VARIANTS: Record<DataModelingJobStatus, 'success' | 'destructive' | 'warning' | 'default'> = {
    Completed: 'success',
    Failed: 'destructive',
    Running: 'warning',
    Cancelled: 'default',
    Skipped: 'default',
}

interface RowCellContext {
    row: { original: ModelRow }
}

function kindLabel({ view, node }: ModelRow): string {
    const kind =
        view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT
            ? 'Endpoint'
            : view.is_materialized
              ? 'Materialized view'
              : 'View'
    const downstreamCount = node?.downstream_count ?? 0
    return downstreamCount > 0 ? `${kind} · feeds ${pluralize(downstreamCount, 'model')}` : kind
}

function nameLabel({ view }: ModelRow): string {
    const endpointModel =
        view.origin === DataWarehouseSavedQueryOrigin.ENDPOINT ? parseEndpointModelName(view.name) : null
    return endpointModel ? `${endpointModel.endpointName} v${endpointModel.version}` : view.name
}

function detailText(row: ModelRow): string | null {
    const problemDetail = subjectDetail(row)
    if (problemDetail) {
        return problemDetail
    }
    const interval = row.node?.sync_interval
    return row.view.is_materialized && interval ? `Refreshes every ${CADENCE_LABELS[interval]}` : null
}

function RunDots({ row }: { row: ModelRow }): JSX.Element | null {
    const runs = row.view.run_history?.slice(0, RUN_HISTORY_LENGTH).reverse() ?? []
    if (runs.length === 0) {
        return null
    }
    return (
        <span className="flex gap-0.5" aria-label="Recent runs, oldest first">
            {runs.map((run, index) => (
                <Tooltip key={index}>
                    <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                        <Dot variant={RUN_DOT_VARIANTS[run.status] ?? 'default'} />
                    </TooltipTrigger>
                    <TooltipContent>
                        {run.timestamp ? `${run.status}, ${humanFriendlyDetailedTime(run.timestamp)}` : run.status}
                    </TooltipContent>
                </Tooltip>
            ))}
        </span>
    )
}

function LastRunTime({ row }: { row: ModelRow }): JSX.Element {
    const since = row.materialization?.kind === 'behind' ? subjectSince(row) : null
    const lastRunAt = row.node?.last_run_at ?? row.view.last_run_at
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {since?.kind === 'overdue' ? since.label : lastRunAt ? <TZLabel time={lastRunAt} /> : 'Never run'}
        </Text>
    )
}

function LastRun({ row }: { row: ModelRow }): JSX.Element {
    if (!row.view.is_materialized) {
        return (
            <Text size="xs" variant="muted" className="whitespace-nowrap">
                Runs on read
            </Text>
        )
    }
    return (
        <div className="flex flex-col gap-1">
            <RunDots row={row} />
            <LastRunTime row={row} />
        </div>
    )
}

function Detail({ row }: { row: ModelRow }): JSX.Element | null {
    const detail = detailText(row)
    if (!detail) {
        return null
    }
    return (
        <Text size="xs" variant="muted" className="line-clamp-2" title={detail}>
            {detail}
        </Text>
    )
}

function StatusBadges({ row }: { row: ModelRow }): JSX.Element | null {
    if (!rowNeedsAttention(row)) {
        return null
    }
    return (
        <ModelsOverviewProblemBadges
            subject={row}
            checksHref={row.node ? urls.nodeDetail(row.node.id, 'data-quality') : null}
        />
    )
}

function RowActions({ row }: { row: ModelRow }): JSX.Element {
    return (
        <div className="flex items-center gap-2 @min-[40rem]/main-content:justify-end">
            {rowNeedsAttention(row) && <ModelsOverviewNextStep subject={row} />}
            <ModelsListRowActions view={row.view} />
        </div>
    )
}

function NameCell({ row }: { row: ModelRow }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 flex-col">
                <Button
                    variant="link"
                    size="inline"
                    className="self-start font-medium text-foreground"
                    render={<LinkPrimitive to={modelRowHref(row)} />}
                    data-attr="models-list-name"
                >
                    {nameLabel(row)}
                </Button>
                <Text size="xs" variant="muted">
                    {kindLabel(row)}
                </Text>
            </div>
            <div className={`${NARROW_ONLY} flex flex-col gap-1`}>
                <StatusBadges row={row} />
                <Detail row={row} />
                <LastRun row={row} />
                <div className="pt-1">
                    <RowActions row={row} />
                </div>
            </div>
        </div>
    )
}

const COLUMNS: DataTableProps<ModelRow, unknown>['columns'] = [
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }: RowCellContext) => <NameCell row={row.original} />,
    },
    {
        id: 'status',
        header: () => <span className={WIDE_ONLY}>Status</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} w-max`}>
                <StatusBadges row={row.original} />
            </span>
        ),
    },
    {
        id: 'detail',
        header: () => <span className={WIDE_ONLY}>Detail</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} min-w-48 max-w-96`}>
                <Detail row={row.original} />
            </span>
        ),
    },
    {
        id: 'last-run',
        header: () => <span className={WIDE_ONLY}>Last run</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={WIDE_ONLY_BLOCK}>
                <LastRun row={row.original} />
            </span>
        ),
    },
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: RowCellContext) => (
            <span className={WIDE_ONLY_BLOCK}>
                <RowActions row={row.original} />
            </span>
        ),
    },
]

const NO_MATCHES = (
    <Empty>
        <EmptyHeader>
            <EmptyTitle>No models match your search</EmptyTitle>
            <EmptyDescription>Clear the search or pick another type.</EmptyDescription>
        </EmptyHeader>
    </Empty>
)

function ModelsTable(): JSX.Element {
    const { visibleRows, filteredRows, currentPage, pageCount } = useValues(modelsListLogic)
    const { setPage } = useActions(modelsListLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    useHoldTallestHeight(containerRef, contentRef, pageCount > 1)

    return (
        <div ref={containerRef} data-attr="models-list-table">
            <div ref={contentRef}>
                <DataTable columns={COLUMNS} data={visibleRows} size="sm" fullWidth empty={NO_MATCHES} />
                {pageCount > 1 && (
                    <ModelsListPagination
                        currentPage={currentPage}
                        pageCount={pageCount}
                        pageSize={MODELS_LIST_PAGE_SIZE}
                        total={filteredRows.length}
                        onPageChange={setPage}
                    />
                )}
            </div>
        </div>
    )
}

function SuggestionsCallout(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { suggestionAccepted } = useActions(viewsTabLogic)
    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return null
    }
    return (
        <SuggestedModelsStrip
            onAccepted={(suggestion) =>
                suggestionAccepted(
                    suggestion.subject_id,
                    suggestion.kind === WarehouseSuggestionKindEnumApi.Materialize
                )
            }
        />
    )
}

function LoadErrors(): JSX.Element {
    const { modelsFailed, overviewError } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)
    return (
        <>
            {modelsFailed && (
                <ModelsOverviewErrorCallout
                    message="Your models could not be loaded. Try again, and if it keeps failing, refresh the page."
                    onRetry={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    dataAttr="models-list-models-error"
                />
            )}
            {overviewError && (
                <ModelsOverviewErrorCallout
                    message="Data quality checks could not be loaded, so failing checks are not shown on your models."
                    onRetry={() => loadOverview()}
                    dataAttr="models-list-checks-error"
                />
            )}
        </>
    )
}

export function ModelsList(): JSX.Element {
    const { allModelRows, modelsFirstLoading, nothingNeedsAttention } = useValues(modelsListLogic)
    const { modelsFailed } = useValues(modelsOverviewLogic)
    const { editingAccessControlView, accessControlModalOpen } = useValues(viewsTabLogic)
    const { closeAccessControlModal } = useActions(viewsTabLogic)
    const loading = modelsFirstLoading && allModelRows.length === 0

    return (
        <section aria-labelledby={HEADING_ID} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                    <span>Models</span>
                    {allModelRows.length > 0 && (
                        <span translate="no" className="ml-2 font-normal text-muted-foreground">
                            {allModelRows.length}
                        </span>
                    )}
                </Heading>
                <ModelsListSearch />
            </div>
            {nothingNeedsAttention && allModelRows.length > 0 && <ModelsListHealthyLine />}
            <SuggestionsCallout />
            <LoadErrors />
            <ModelsListHealthFilter />
            {loading &&
                Array.from({ length: SKELETON_ROWS }, (_, index) => <Skeleton key={index} className="h-8 w-full" />)}
            {!loading && (allModelRows.length > 0 || !modelsFailed) && <ModelsTable />}
            {editingAccessControlView && (
                <AccessControlObjectModal
                    isOpen={accessControlModalOpen}
                    onClose={closeAccessControlModal}
                    resource={AccessControlResourceType.WarehouseView}
                    resource_id={editingAccessControlView.id}
                    title={editingAccessControlView.name}
                    description="Control who can query this view. Users without access won't see it and queries referencing it will fail for them."
                />
            )}
        </section>
    )
}
