import { useActions, useValues } from 'kea'
import { MouseEvent, useRef } from 'react'

import { IconCheckCircle, IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Button,
    Checkbox,
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

import { sortDirectionFor } from '../catalogSort'
import { CatalogTableRow, TablesSortColumn, passingChecks, rowIsExpandable } from '../catalogTableRows'
import { TABLES_PAGE_SIZE, catalogTablesLogic } from '../catalogTablesLogic'
import { PageSelectionCheckbox } from '../components/PageSelectionCheckbox'
import { SortHeadProps, SortableTableHead } from '../components/SortableTableHead'
import { CatalogTableRefresh } from './CatalogTableRefresh'
import { CatalogTableRowMenu } from './CatalogTableRowMenu'
import { CatalogTablesPagination } from './CatalogTablesPagination'
import { CatalogTableTrust } from './CatalogTableTrust'
import { MutedCellText } from './MutedCellText'
import { TableChecksPanel } from './TableChecksPanel'

const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const COLUMN_COUNT = 7
const INTERACTIVE_SELECTOR = 'a, button, input, label, [role="checkbox"]'

function checksPanelId(row: CatalogTableRow): string {
    return `data-catalog-tables-checks-${row.key}`
}

function ChecksLabel({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const counts = passingChecks(row)
    if (row.checkGroup && runningSubjectKey === row.checkGroup.subjectKey) {
        return (
            <span className="flex items-center gap-1 whitespace-nowrap">
                <Spinner />
                Running
            </span>
        )
    }
    if (!counts) {
        return null
    }
    return (
        <span className="whitespace-nowrap tabular-nums">{`${counts.total - counts.failing}/${counts.total} passing`}</span>
    )
}

function ChecksToggle({ row, expanded }: { row: CatalogTableRow; expanded: boolean }): JSX.Element {
    const { toggleRowExpanded } = useActions(catalogTablesLogic)
    if (!passingChecks(row)) {
        return <MutedCellText>No checks</MutedCellText>
    }
    if (!rowIsExpandable(row)) {
        return <ChecksLabel row={row} />
    }
    return (
        <Button
            size="xs"
            aria-expanded={expanded}
            aria-controls={checksPanelId(row)}
            aria-label={`${expanded ? 'Hide' : 'Show'} checks for ${row.name}`}
            className="-ml-1.5 gap-1"
            onClick={() => toggleRowExpanded(row)}
            data-attr="data-catalog-tables-expand"
        >
            <ChecksLabel row={row} />
            <IconChevronRight
                aria-hidden
                className={cn('size-3 transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
            />
        </Button>
    )
}

function StatusBadges({ row }: { row: CatalogTableRow }): JSX.Element {
    if (row.problems.length > 0) {
        return <ModelsOverviewProblemBadges subject={row.health} />
    }
    return (
        <Badge variant="success">
            <IconCheckCircle aria-hidden />
            Healthy
        </Badge>
    )
}

function NameCell({ row, expanded }: { row: CatalogTableRow; expanded: boolean }): JSX.Element {
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
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                <div className="flex flex-wrap items-center gap-2">
                    <StatusBadges row={row} />
                    <ChecksToggle row={row} expanded={expanded} />
                </div>
                <CatalogTableTrust row={row} />
            </div>
        </div>
    )
}

function isPlainRowClick(event: MouseEvent<HTMLTableRowElement>): boolean {
    const target = event.target
    return target instanceof Element && event.currentTarget.contains(target) && !target.closest(INTERACTIVE_SELECTOR)
}

function TableRows({
    row,
    expanded,
    selected,
}: {
    row: CatalogTableRow
    expanded: boolean
    selected: boolean
}): JSX.Element {
    const { toggleRowExpanded, toggleRowSelected } = useActions(catalogTablesLogic)
    const expandable = rowIsExpandable(row)
    const toggleUnlessInteractive = (event: MouseEvent<HTMLTableRowElement>): void => {
        if (expandable && isPlainRowClick(event)) {
            toggleRowExpanded(row)
        }
    }
    return (
        <>
            <TableRow
                className={cn(expandable && 'cursor-pointer')}
                data-state={selected ? 'selected' : undefined}
                onClick={toggleUnlessInteractive}
                data-attr="data-catalog-tables-row"
            >
                <TableCell valign="top" className="w-0 pr-0">
                    <Checkbox
                        aria-label={`Select ${row.name}`}
                        checked={selected}
                        onCheckedChange={() => toggleRowSelected(row.key)}
                        data-attr="data-catalog-tables-select"
                    />
                </TableCell>
                <TableCell expand valign="top">
                    <NameCell row={row} expanded={expanded} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <StatusBadges row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <ChecksToggle row={row} expanded={expanded} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {row.certification ? <CatalogTableTrust row={row} /> : <MutedCellText>Not certified</MutedCellText>}
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <CatalogTableRefresh row={row} />
                </TableCell>
                <TableCell valign="top" align="right" className="w-0">
                    <CatalogTableRowMenu row={row} />
                </TableCell>
            </TableRow>
            {expanded && (
                <TableRow id={checksPanelId(row)}>
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
    const { visibleRows, filteredRows, currentPage, pageCount, expandedRowKeys, selectedRowKeys, sort } =
        useValues(catalogTablesLogic)
    const { setPage, setRowsSelected, toggleSort } = useActions(catalogTablesLogic)
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const anyExpanded = visibleRows.some((row) => expandedRowKeys.includes(row.key))
    useHoldTallestHeight(containerRef, contentRef, pageCount > 1 && !anyExpanded)
    const sortProps = (column: TablesSortColumn): SortHeadProps => ({
        direction: sortDirectionFor(sort, column),
        onToggle: () => toggleSort(column),
        dataAttr: `data-catalog-tables-sort-${column}`,
    })

    return (
        <div ref={containerRef} data-attr="data-catalog-tables-table">
            <div ref={contentRef}>
                <Table fullWidth size="sm">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-0 pr-0">
                                <PageSelectionCheckbox
                                    label="Select all tables on this page"
                                    pageIds={visibleRows.map((row) => row.key)}
                                    selectedIds={selectedRowKeys}
                                    onChange={setRowsSelected}
                                />
                            </TableHead>
                            <SortableTableHead label="Name" expand {...sortProps('name')} />
                            <SortableTableHead label="Status" className={WIDE_ONLY_CELL} {...sortProps('status')} />
                            <SortableTableHead label="Checks" className={WIDE_ONLY_CELL} {...sortProps('checks')} />
                            <SortableTableHead label="Trust" className={WIDE_ONLY_CELL} {...sortProps('trust')} />
                            <SortableTableHead
                                label="Last refresh"
                                className={WIDE_ONLY_CELL}
                                {...sortProps('refresh')}
                            />
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
                                <TableRows
                                    key={row.key}
                                    row={row}
                                    expanded={expandedRowKeys.includes(row.key)}
                                    selected={selectedRowKeys.includes(row.key)}
                                />
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
