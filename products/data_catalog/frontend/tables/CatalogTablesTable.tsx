import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ModelsOverviewProblemBadges } from 'products/data_modeling/frontend/ModelsOverviewProblemBadges'
import { useHoldTallestHeight } from 'products/data_modeling/frontend/useHoldTallestHeight'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CatalogTableRow } from '../catalogTableRows'
import { TABLES_PAGE_SIZE, catalogTablesLogic } from '../catalogTablesLogic'
import { CertificationStatusTag, certificationStatusTag } from '../certificationStatusTag'
import { CatalogTableRefresh } from './CatalogTableRefresh'
import { CatalogTableRowMenu } from './CatalogTableRowMenu'
import { CatalogTablesPagination } from './CatalogTablesPagination'
import { TableChecksPanel } from './TableChecksPanel'

const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const COLUMN_COUNT = 7

const TRUST_BADGE_VARIANTS: Record<CertificationStatusTag['type'], 'success' | 'warning' | 'default'> = {
    success: 'success',
    warning: 'warning',
    muted: 'default',
}

function ChecksSummary({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const group = row.checkGroup
    if (!group) {
        return null
    }
    if (runningSubjectKey === group.subjectKey) {
        return (
            <Text size="xs" variant="muted" className="flex items-center gap-1 whitespace-nowrap">
                <Spinner />
                Running
            </Text>
        )
    }
    const passing = group.checks.filter((check) => check.last_status === 'passed').length
    return <span className="whitespace-nowrap tabular-nums">{`${passing}/${group.checks.length} passing`}</span>
}

function TrustBadge({ row }: { row: CatalogTableRow }): JSX.Element | null {
    if (!row.certification) {
        return null
    }
    const tag = certificationStatusTag(row.certification)
    return <Badge variant={TRUST_BADGE_VARIANTS[tag.type]}>{tag.label}</Badge>
}

function StatusBadges({ row }: { row: CatalogTableRow }): JSX.Element | null {
    return row.problems.length > 0 ? <ModelsOverviewProblemBadges subject={row.health} /> : null
}

function NameCell({ row }: { row: CatalogTableRow }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 flex-col">
                {row.detailUrl ? (
                    <Button
                        variant="link"
                        size="inline"
                        className="self-start font-medium text-foreground"
                        render={<LinkPrimitive to={row.detailUrl} />}
                        data-attr="data-catalog-tables-name"
                    >
                        {row.name}
                    </Button>
                ) : (
                    <span className="font-medium">{row.name}</span>
                )}
                <Text size="xs" variant="muted">
                    {row.subtitle}
                </Text>
            </div>
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1 empty:hidden')}>
                <StatusBadges row={row} />
                <div className="flex flex-wrap items-center gap-2 empty:hidden">
                    <ChecksSummary row={row} />
                    <TrustBadge row={row} />
                </div>
                <CatalogTableRefresh row={row} />
            </div>
        </div>
    )
}

function ExpandButton({ row, expanded }: { row: CatalogTableRow; expanded: boolean }): JSX.Element {
    const { toggleRowExpanded } = useActions(catalogTablesLogic)
    const label = `${expanded ? 'Hide' : 'Show'} checks for ${row.name}`
    return (
        <Button
            size="icon-sm"
            aria-label={label}
            aria-expanded={expanded}
            className="text-muted-foreground"
            onClick={() => toggleRowExpanded(row.key)}
            data-attr="data-catalog-tables-expand"
        >
            <IconChevronRight
                className={cn('transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
            />
        </Button>
    )
}

function TableRows({ row, expanded }: { row: CatalogTableRow; expanded: boolean }): JSX.Element {
    return (
        <>
            <TableRow data-attr="data-catalog-tables-row">
                <TableCell valign="top" className="w-0 pr-0">
                    <ExpandButton row={row} expanded={expanded} />
                </TableCell>
                <TableCell expand valign="top">
                    <NameCell row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <StatusBadges row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <ChecksSummary row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <TrustBadge row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <CatalogTableRefresh row={row} />
                </TableCell>
                <TableCell valign="top" align="right" className="w-0">
                    <CatalogTableRowMenu row={row} />
                </TableCell>
            </TableRow>
            {expanded && (
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <TableChecksPanel row={row} />
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

function NoMatches(): JSX.Element {
    const { clearFilters, setScope, setSearch } = useActions(catalogTablesLogic)
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No tables match</EmptyTitle>
                <EmptyDescription>Change the search or the filters to see more tables.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                        clearFilters()
                        setScope('all')
                        setSearch('')
                    }}
                    data-attr="data-catalog-tables-show-all"
                >
                    Show all tables
                </Button>
            </EmptyContent>
        </Empty>
    )
}

export function CatalogTablesTable(): JSX.Element {
    const { visibleRows, filteredRows, currentPage, pageCount, expandedRowKeys } = useValues(catalogTablesLogic)
    const { setPage } = useActions(catalogTablesLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const anyExpanded = visibleRows.some((row) => expandedRowKeys.includes(row.key))
    useHoldTallestHeight(containerRef, contentRef, pageCount > 1 && !anyExpanded)

    return (
        <div ref={containerRef} data-attr="data-catalog-tables-table">
            <div ref={contentRef}>
                <Table fullWidth size="sm">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-0 pr-0">
                                <span className="sr-only">Checks</span>
                            </TableHead>
                            <TableHead expand>Name</TableHead>
                            <TableHead className={WIDE_ONLY_CELL}>Status</TableHead>
                            <TableHead className={WIDE_ONLY_CELL}>Checks</TableHead>
                            <TableHead className={WIDE_ONLY_CELL}>Trust</TableHead>
                            <TableHead className={WIDE_ONLY_CELL}>Last refresh</TableHead>
                            <TableHead className="w-0">
                                <span className="sr-only">Actions</span>
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    {visibleRows.length === 0 ? (
                        <TableEmpty>
                            <NoMatches />
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {visibleRows.map((row) => (
                                <TableRows key={row.key} row={row} expanded={expandedRowKeys.includes(row.key)} />
                            ))}
                        </TableBody>
                    )}
                </Table>
                {pageCount > 1 && (
                    <CatalogTablesPagination
                        currentPage={currentPage}
                        pageCount={pageCount}
                        pageSize={TABLES_PAGE_SIZE}
                        total={filteredRows.length}
                        onPageChange={setPage}
                    />
                )}
            </div>
        </div>
    )
}
