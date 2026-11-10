import { useActions, useValues } from 'kea'
import { MouseEvent } from 'react'

import { IconCheckCircle } from '@posthog/icons'
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
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ModelsOverviewProblemBadges } from 'products/data_modeling/frontend/ModelsOverviewProblemBadges'

import { CatalogTableRow, dataQualityUrl, passingChecks } from '../catalogTableRows'
import { TABLES_PAGE_SIZE, catalogTablesLogic } from '../catalogTablesLogic'
import { CatalogChecksSummary } from '../components/CatalogChecksSummary'
import { PageSelectionCheckbox } from '../components/PageSelectionCheckbox'
import { CatalogTableFreshness } from './CatalogTableFreshness'
import { CatalogTableRowMenu } from './CatalogTableRowMenu'
import { CatalogTablesPagination } from './CatalogTablesPagination'
import { CatalogTablesSortableHead } from './CatalogTablesSortableHead'
import { CatalogTableTrust } from './CatalogTableTrust'
import { MutedCellText } from './MutedCellText'

const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const INTERACTIVE_SELECTOR = 'a, button, input, label, [role="checkbox"]'

function ChecksCell({ row }: { row: CatalogTableRow }): JSX.Element {
    if (!passingChecks(row)) {
        return <MutedCellText>No checks</MutedCellText>
    }
    return (
        <Button
            variant="link-foreground"
            size="inline"
            className="self-start"
            render={<LinkPrimitive to={dataQualityUrl(row.name)} />}
            data-attr="data-catalog-tables-checks-link"
        >
            <CatalogChecksSummary row={row} />
        </Button>
    )
}

function StatusBadges({ row }: { row: CatalogTableRow }): JSX.Element {
    if (row.problems.length > 0) {
        return <ModelsOverviewProblemBadges statuses={row.attention.statuses} />
    }
    return (
        <Badge variant="success">
            <IconCheckCircle aria-hidden />
            Healthy
        </Badge>
    )
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
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                <div className="flex flex-wrap items-center gap-2">
                    <StatusBadges row={row} />
                    <ChecksCell row={row} />
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

function CatalogTablesTableRow({ row, selected }: { row: CatalogTableRow; selected: boolean }): JSX.Element {
    const { certificationsLoadFailed } = useValues(catalogTablesLogic)
    const { openRow, toggleRowSelected } = useActions(catalogTablesLogic)
    const openUnlessInteractive = (event: MouseEvent<HTMLTableRowElement>): void => {
        if (isPlainRowClick(event)) {
            openRow(row)
        }
    }
    return (
        <TableRow
            className={cn(row.detailUrl && 'cursor-pointer')}
            data-state={selected ? 'selected' : undefined}
            onClick={openUnlessInteractive}
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
                <NameCell row={row} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <StatusBadges row={row} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <ChecksCell row={row} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                {row.certification ? (
                    <CatalogTableTrust row={row} />
                ) : (
                    <MutedCellText>{certificationsLoadFailed ? 'Not loaded' : 'Not certified'}</MutedCellText>
                )}
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <CatalogTableFreshness row={row} />
            </TableCell>
            <TableCell valign="top" align="right" className="w-0">
                <CatalogTableRowMenu row={row} />
            </TableCell>
        </TableRow>
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
    const { visibleRows, filteredRows, currentPage, pageCount, selectedRowKeys } = useValues(catalogTablesLogic)
    const { setPage, setRowsSelected } = useActions(catalogTablesLogic)
    return (
        <div data-attr="data-catalog-tables-table">
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
                        <CatalogTablesSortableHead column="name" label="Name" expand />
                        <CatalogTablesSortableHead column="status" label="Status" className={WIDE_ONLY_CELL} />
                        <CatalogTablesSortableHead column="checks" label="Checks" className={WIDE_ONLY_CELL} />
                        <CatalogTablesSortableHead column="trust" label="Trust" className={WIDE_ONLY_CELL} />
                        <CatalogTablesSortableHead column="freshness" label="Freshness" className={WIDE_ONLY_CELL} />
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
                            <CatalogTablesTableRow
                                key={row.key}
                                row={row}
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
    )
}
