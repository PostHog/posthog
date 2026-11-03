import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Button,
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

import { sortDirectionFor } from '../catalogSort'
import { SortHeadProps, SortableTableHead } from '../components/SortableTableHead'
import { usePagedItems } from '../components/usePagedItems'
import {
    DEFAULT_RELATIONSHIPS_FILTERS,
    RelationshipRow,
    RelationshipsSortColumn,
    relationshipTableRef,
    relationshipsLogic,
} from '../relationshipsLogic'
import { CatalogTablesPagination } from '../tables/CatalogTablesPagination'
import { CatalogRelationshipActions } from './CatalogRelationshipActions'

const RELATIONSHIPS_PAGE_SIZE = 20
const WIDE_ONLY_CELL = 'hidden @min-[40rem]/main-content:table-cell'
const NARROW_ONLY = '@min-[40rem]/main-content:hidden'
const EXTRA_WIDE_ONLY_CELL = 'hidden @min-[72rem]/main-content:table-cell'
const BELOW_EXTRA_WIDE = '@min-[72rem]/main-content:hidden'
const COLUMN_COUNT = 8

const STATUS_BADGES: Record<
    RelationshipRow['rowStatus'],
    { label: string; variant: 'warning' | 'success' | 'destructive' }
> = {
    pending: { label: 'Pending', variant: 'warning' },
    active: { label: 'Active', variant: 'success' },
    rejected: { label: 'Rejected', variant: 'destructive' },
}

function hasDetail(row: RelationshipRow): boolean {
    return !!row.reasoning || !!row.evidence || !!row.rejectionReason
}

function TableRefText({ table, refKey }: { table: string; refKey: string }): JSX.Element {
    const value = relationshipTableRef(table, refKey)
    return (
        <span title={value} className="block max-w-56 truncate font-mono text-xs">
            {value}
        </span>
    )
}

function StatusBadges({ row }: { row: RelationshipRow }): JSX.Element {
    const status = STATUS_BADGES[row.rowStatus]
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={status.variant}>{status.label}</Badge>
            {row.viaCatalog && <Badge variant="info">Via catalog</Badge>}
        </div>
    )
}

function confidenceLabel(confidence: number | null): string {
    return confidence != null ? `${Math.round(confidence * 100)}%` : ''
}

function SourceCell({ row }: { row: RelationshipRow }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <TableRefText table={row.sourceTableName} refKey={row.sourceTableKey} />
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                <Text size="xs" variant="muted" className="flex min-w-0 items-center gap-1">
                    <span className="shrink-0">Joins to</span>
                    <TableRefText table={row.joiningTableName} refKey={row.joiningTableKey} />
                </Text>
                <StatusBadges row={row} />
            </div>
            <div className={cn(BELOW_EXTRA_WIDE, 'flex flex-col gap-0.5 empty:hidden')}>
                {row.confidence != null && (
                    <Text size="xs" variant="muted">
                        {`${confidenceLabel(row.confidence)} confidence`}
                    </Text>
                )}
                {row.reviewedBy && (
                    <Text size="xs" variant="muted">
                        {`Reviewed by ${row.reviewedBy}`}
                    </Text>
                )}
            </div>
        </div>
    )
}

function DetailSection({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Text size="xs" variant="muted">
                {label}
            </Text>
            {children}
        </div>
    )
}

function RelationshipDetail({ row }: { row: RelationshipRow }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-2">
            {row.reasoning && (
                <DetailSection label="Reasoning">
                    <Text size="xs">{row.reasoning}</Text>
                </DetailSection>
            )}
            {row.rejectionReason && (
                <DetailSection label="Rejection reason">
                    <Text size="xs">{row.rejectionReason}</Text>
                </DetailSection>
            )}
            {row.evidence != null && (
                <DetailSection label="Evidence">
                    <pre className="m-0 max-h-80 overflow-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
                        {JSON.stringify(row.evidence, null, 2)}
                    </pre>
                </DetailSection>
            )}
        </div>
    )
}

function ExpandButton({
    row,
    expanded,
    onToggle,
}: {
    row: RelationshipRow
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    return (
        <Button
            size="icon-sm"
            aria-label={`${expanded ? 'Hide' : 'Show'} details for ${row.fieldName}`}
            aria-expanded={expanded}
            className="text-muted-foreground"
            onClick={onToggle}
            data-attr="data-catalog-relationships-expand"
        >
            <IconChevronRight
                className={cn('transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
            />
        </Button>
    )
}

function RelationshipRows({
    row,
    expanded,
    onToggle,
}: {
    row: RelationshipRow
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    return (
        <>
            <TableRow data-attr="data-catalog-relationships-row">
                <TableCell valign="top" className="w-0 pr-0">
                    {hasDetail(row) && <ExpandButton row={row} expanded={expanded} onToggle={onToggle} />}
                </TableCell>
                <TableCell expand valign="top">
                    <SourceCell row={row} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <TableRefText table={row.joiningTableName} refKey={row.joiningTableKey} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <Text size="xs">{row.fieldName}</Text>
                </TableCell>
                <TableCell valign="top" className={cn(EXTRA_WIDE_ONLY_CELL, 'tabular-nums')}>
                    <Text size="xs">{confidenceLabel(row.confidence)}</Text>
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <StatusBadges row={row} />
                </TableCell>
                <TableCell valign="top" className={EXTRA_WIDE_ONLY_CELL}>
                    <Text size="xs" variant={row.reviewedBy ? 'default' : 'muted'}>
                        {row.reviewedBy || '-'}
                    </Text>
                </TableCell>
                <TableCell valign="top" align="right" className="w-0">
                    <CatalogRelationshipActions row={row} />
                </TableCell>
            </TableRow>
            {expanded && (
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <RelationshipDetail row={row} />
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

function NoRelationships(): JSX.Element {
    const { setFilters } = useActions(relationshipsLogic)
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No relationships match</EmptyTitle>
                <EmptyDescription>Change the search or the status filter to see more relationships.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setFilters(DEFAULT_RELATIONSHIPS_FILTERS)}
                    data-attr="data-catalog-relationships-show-all"
                >
                    Show all relationships
                </Button>
            </EmptyContent>
        </Empty>
    )
}

export function CatalogRelationshipsTable(): JSX.Element {
    const { sortedRows, sort } = useValues(relationshipsLogic)
    const { toggleSort } = useActions(relationshipsLogic)
    const { pageItems, currentPage, pageCount, setPage } = usePagedItems(sortedRows, RELATIONSHIPS_PAGE_SIZE)
    const sortProps = (column: RelationshipsSortColumn): SortHeadProps => ({
        direction: sortDirectionFor(sort, column),
        onToggle: () => toggleSort(column),
        dataAttr: `data-catalog-relationships-sort-${column}`,
    })
    const [expandedKeys, setExpandedKeys] = useState<string[]>([])
    const toggleExpanded = (key: string): void =>
        setExpandedKeys(
            expandedKeys.includes(key) ? expandedKeys.filter((expanded) => expanded !== key) : [...expandedKeys, key]
        )

    return (
        <div data-attr="data-catalog-relationships-table">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-0 pr-0">
                            <span className="sr-only">Details</span>
                        </TableHead>
                        <SortableTableHead label="Source" expand {...sortProps('source')} />
                        <SortableTableHead label="Joins to" className={WIDE_ONLY_CELL} {...sortProps('joining')} />
                        <SortableTableHead
                            label="Accessor"
                            tooltip="The field added to the source table to reach the joined rows, for example events.person"
                            className={WIDE_ONLY_CELL}
                            {...sortProps('accessor')}
                        />
                        <SortableTableHead
                            label="Confidence"
                            className={EXTRA_WIDE_ONLY_CELL}
                            {...sortProps('confidence')}
                        />
                        <SortableTableHead label="Status" className={WIDE_ONLY_CELL} {...sortProps('status')} />
                        <SortableTableHead
                            label="Reviewed by"
                            className={EXTRA_WIDE_ONLY_CELL}
                            {...sortProps('reviewedBy')}
                        />
                        <TableHead className="w-0">
                            <span className="sr-only">Actions</span>
                        </TableHead>
                    </TableRow>
                </TableHeader>
                {pageItems.length === 0 ? (
                    <TableEmpty>
                        <NoRelationships />
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {pageItems.map((row) => (
                            <RelationshipRows
                                key={row.key}
                                row={row}
                                expanded={expandedKeys.includes(row.key)}
                                onToggle={() => toggleExpanded(row.key)}
                            />
                        ))}
                    </TableBody>
                )}
            </Table>
            {pageCount > 1 && (
                <CatalogTablesPagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={RELATIONSHIPS_PAGE_SIZE}
                    total={sortedRows.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
