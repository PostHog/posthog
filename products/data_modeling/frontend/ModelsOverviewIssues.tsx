import { useActions, useValues } from 'kea'

import { IconClock, IconPauseFilled, IconWarning, IconXCircle } from '@posthog/icons'
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
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ModelsOverviewAttentionFilter } from './ModelsOverviewAttentionFilter'
import { AttentionRow, modelsOverviewLogic } from './modelsOverviewLogic'
import { ModelsOverviewNextStep } from './ModelsOverviewNextStep'
import { ATTENTION_DESCRIPTION, IssueKind, IssueTone } from './overviewIssueCopy'

const WIDE_ONLY = 'hidden @min-[40rem]/main-content:inline'
const WIDE_ONLY_BLOCK = 'hidden @min-[40rem]/main-content:block'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const SKELETON_ROWS = 3
const PAGE_SIZE = 10
const SECTION_ID = 'models-overview-attention-section'
const HEADING_ID = `${SECTION_ID}-heading`
const DESCRIPTION_ID = `${SECTION_ID}-description`

interface RowCellContext {
    row: { original: AttentionRow }
}

const BADGE_VARIANTS: Record<IssueTone, 'destructive' | 'warning'> = {
    danger: 'destructive',
    warning: 'warning',
}

const ISSUE_ICONS: Record<IssueKind, typeof IconClock> = {
    suspended: IconPauseFilled,
    failed: IconXCircle,
    behind: IconClock,
    checks: IconWarning,
}

function ProblemBadges({ row }: { row: AttentionRow }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {row.statuses.map(({ kind, label, tone, tooltip }) => {
                const Icon = ISSUE_ICONS[kind]
                return (
                    <Tooltip key={kind}>
                        <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                            <Badge variant={BADGE_VARIANTS[tone]}>
                                <Icon aria-hidden />
                                {label}
                            </Badge>
                        </TooltipTrigger>
                        <TooltipContent>{tooltip}</TooltipContent>
                    </Tooltip>
                )
            })}
        </div>
    )
}

function NameLink({ row }: { row: AttentionRow }): JSX.Element {
    if (!row.href) {
        return <Text size="xs">{row.name}</Text>
    }
    return (
        <Button
            variant="link"
            size="inline"
            className="self-start font-medium text-foreground"
            render={<LinkPrimitive to={row.href} />}
        >
            {row.name}
        </Button>
    )
}

function DetailText({ row }: { row: AttentionRow }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col">
            {row.detail && (
                <Text size="xs" variant="muted" className="line-clamp-1" title={row.detail}>
                    {row.detail}
                </Text>
            )}
            {row.impact && (
                <Text size="xs" variant="muted" className="line-clamp-1">
                    {row.impact}
                </Text>
            )}
        </div>
    )
}

function SinceText({ row }: { row: AttentionRow }): JSX.Element | null {
    const { since } = row
    if (!since) {
        return null
    }
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {since.kind === 'behind' ? (
                since.label
            ) : (
                <>
                    {since.label && `${since.label} `}
                    <TZLabel time={since.time} />
                </>
            )}
        </Text>
    )
}

function NarrowLines({ row }: { row: AttentionRow }): JSX.Element {
    return (
        <div className={`${NARROW_ONLY} flex flex-col gap-1`}>
            <ProblemBadges row={row} />
            <DetailText row={row} />
            <SinceText row={row} />
            <div className="pt-1">
                <ModelsOverviewNextStep nextStep={row.nextStep} />
            </div>
        </div>
    )
}

const COLUMNS: DataTableProps<AttentionRow, unknown>['columns'] = [
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }: RowCellContext) => (
            <div className="flex min-w-0 flex-col gap-1">
                <NameLink row={row.original} />
                <NarrowLines row={row.original} />
            </div>
        ),
    },
    {
        id: 'problems',
        header: () => <span className={WIDE_ONLY}>Problems</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} w-max`}>
                <ProblemBadges row={row.original} />
            </span>
        ),
    },
    {
        id: 'detail',
        header: () => <span className={WIDE_ONLY}>Detail</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={`${WIDE_ONLY_BLOCK} min-w-48 max-w-96`}>
                <DetailText row={row.original} />
            </span>
        ),
    },
    {
        id: 'since',
        header: () => <span className={WIDE_ONLY}>Since</span>,
        enableSorting: false,
        cell: ({ row }: RowCellContext) => (
            <span className={WIDE_ONLY}>
                <SinceText row={row.original} />
            </span>
        ),
    },
    {
        id: 'next-step',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }: RowCellContext) => (
            <span className={WIDE_ONLY}>
                <ModelsOverviewNextStep nextStep={row.original.nextStep} />
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

function UnlistedFailingNote({ count }: { count: number }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<p className="m-0" />} data-attr="models-overview-unlisted-checks">
            {`${pluralize(count, 'more view or table', 'more views and tables')} ${count === 1 ? 'has' : 'have'} failing checks. `}
            <LinkPrimitive to={urls.models('data-quality')}>View all checks</LinkPrimitive>
        </Text>
    )
}

export function ModelsOverviewIssues(): JSX.Element {
    const {
        attentionRows,
        attentionCounts,
        filteredAttentionRows,
        unlistedFailingSubjectCount,
        modelsFailed,
        overviewError,
        modelsFirstLoading,
        checksFirstLoading,
    } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries, loadOverview } = useActions(modelsOverviewLogic)

    const loading = (modelsFirstLoading || checksFirstLoading) && attentionRows.length === 0

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
                        {attentionCounts.all > 0 && (
                            <span translate="no" className="ml-2 font-normal text-muted-foreground">
                                {attentionCounts.all}
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
                <Text size="xs" variant="muted" render={<p id={DESCRIPTION_ID} className="m-0" />}>
                    {ATTENTION_DESCRIPTION}
                </Text>
            </div>
            <ModelsOverviewAttentionFilter />
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
            {filteredAttentionRows.length > 0 && (
                <div data-attr="models-overview-attention">
                    <DataTable
                        columns={COLUMNS}
                        data={filteredAttentionRows}
                        pageSize={PAGE_SIZE}
                        size="sm"
                        fullWidth
                    />
                </div>
            )}
            {unlistedFailingSubjectCount > 0 && <UnlistedFailingNote count={unlistedFailingSubjectCount} />}
        </section>
    )
}
