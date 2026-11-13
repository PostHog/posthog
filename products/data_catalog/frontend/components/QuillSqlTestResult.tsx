import { useState } from 'react'

import {
    Button,
    Item,
    ItemContent,
    ItemDescription,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    cn,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CatalogTablesPagination } from '../tables/CatalogTablesPagination'
import { QuillResultCell } from './QuillResultCell'
import type { SqlTestResultProps } from './SqlTestResult'

const SINGLE_VALUE_MAX_FRACTION_DIGITS = 6

const PREVIEW_PAGE_SIZE = 5

function PreviewTable({ columns, rows }: { columns: string[]; rows: unknown[][] }): JSX.Element {
    const [page, setPage] = useState(1)
    const pageCount = Math.ceil(rows.length / PREVIEW_PAGE_SIZE)
    const currentPage = Math.min(page, Math.max(pageCount, 1))
    const pageRows = rows.slice((currentPage - 1) * PREVIEW_PAGE_SIZE, currentPage * PREVIEW_PAGE_SIZE)

    return (
        <div className="flex flex-col gap-2 rounded-md border border-border">
            <div className="overflow-x-auto">
                <Table size="sm" fullWidth>
                    <TableHeader>
                        <TableRow>
                            {columns.map((column, index) => (
                                <TableHead key={index}>{column}</TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {pageRows.map((row, rowIndex) => (
                            <TableRow key={rowIndex}>
                                {columns.map((_, index) => (
                                    <TableCell key={index}>
                                        <QuillResultCell value={row[index]} />
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            {pageCount > 1 && (
                <CatalogTablesPagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={PREVIEW_PAGE_SIZE}
                    total={rows.length}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}

function previewFootnote(stale: boolean, hasMore: boolean, rowCount: number): string {
    if (stale) {
        return 'The query changed since the last test.'
    }
    return hasMore ? `From your last test. Showing the first ${rowCount} rows.` : 'From your last test.'
}

export function QuillSqlTestResult({ preview, unit, stale, loading, onAddUnit }: SqlTestResultProps): JSX.Element {
    const isSingleValue = preview.rows.length === 1 && preview.columns.length === 1
    const singleValue = isSingleValue ? preview.rows[0][0] : undefined

    return (
        <div className={cn('flex flex-col gap-2', (stale || loading) && 'opacity-60')} aria-live="polite">
            {preview.warnings.length > 0 && (
                <Item variant="outline" size="sm" tone="warning">
                    <ItemContent>
                        <ItemDescription>This result may be incomplete:</ItemDescription>
                        <ul className="m-0 list-disc pl-5 text-xs">
                            {preview.warnings.map((warning) => (
                                <li key={warning}>{warning}</li>
                            ))}
                        </ul>
                    </ItemContent>
                </Item>
            )}
            {preview.rows.length === 0 ? (
                <Text size="xs" variant="muted" className="m-0">
                    The query returned no rows.
                </Text>
            ) : isSingleValue && typeof singleValue === 'number' ? (
                <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-2xl font-semibold tabular-nums" translate="no">
                        {humanFriendlyNumber(singleValue, SINGLE_VALUE_MAX_FRACTION_DIGITS)}
                    </span>
                    {unit.trim() ? (
                        <Text size="xs" variant="muted" render={<span />}>
                            {unit.trim()}
                        </Text>
                    ) : (
                        <Text size="xs" render={<span />}>
                            <Button
                                variant="link"
                                size="inline"
                                onClick={onAddUnit}
                                data-attr="data-catalog-new-metric-add-unit"
                            >
                                Add a unit
                            </Button>
                        </Text>
                    )}
                </div>
            ) : isSingleValue ? (
                <Text size="xs" render={<div className="m-0 flex flex-wrap items-baseline gap-x-2" />}>
                    <span className="text-muted-foreground">{preview.columns[0]}</span>
                    <span className="font-semibold" translate="no">
                        {singleValue == null ? 'NULL' : <QuillResultCell value={singleValue} />}
                    </span>
                </Text>
            ) : (
                <PreviewTable key={preview.sql} columns={preview.columns} rows={preview.rows} />
            )}
            <Text size="xs" variant="muted" render={<span />}>
                {previewFootnote(stale, preview.hasMore, preview.rows.length)}
            </Text>
        </div>
    )
}
