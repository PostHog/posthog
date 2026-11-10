import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Badge,
    Button,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    cn,
} from '@posthog/quill'

import { CustomSqlCodeEditor } from './CustomSqlCodeEditor'
import { CodeEditorInstance, insertOutputColumn } from './customSqlEditor'
import { CustomSqlPreview, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { formatPreviewCell } from './previewCell'
import { QuillCheckCallout } from './QuillCheckCallout'
import { QuillCheckFormField } from './QuillCheckFormField'

const PREVIEW_ROW_LIMIT = 10

function AvailableColumns({ onInsert }: { onInsert: (columnName: string) => void }): JSX.Element {
    const { availableOutputSchema, metricOutputSchemaError, metricOutputSchemaLoading } =
        useValues(dataQualityCheckEditorLogic)
    const { loadMetricOutputSchema } = useActions(dataQualityCheckEditorLogic)

    return (
        <div className="flex flex-col rounded-md border">
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                <div className="flex flex-col">
                    <Text size="xs" weight="medium" className="m-0">
                        Available columns
                    </Text>
                    <Text size="xs" variant="muted" className="m-0">
                        Select a column to insert it into the query.
                    </Text>
                </div>
                {metricOutputSchemaLoading && <Spinner />}
            </div>
            {metricOutputSchemaError ? (
                <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <Text size="xs" variant="muted" className="m-0">
                        Couldn't load the metric output schema. You can still write the query manually.
                    </Text>
                    <Button variant="outline" onClick={() => loadMetricOutputSchema(undefined)}>
                        Retry
                    </Button>
                </div>
            ) : !metricOutputSchemaLoading && availableOutputSchema.length === 0 ? (
                <Text size="xs" variant="muted" className="m-0 px-3 py-2">
                    No output columns were found. You can still write the query manually.
                </Text>
            ) : (
                <div className="flex max-h-40 flex-col overflow-y-auto p-1 scroll-mask-y-4 scroll-py-4">
                    {availableOutputSchema.map((column) => (
                        <Button
                            key={column.name}
                            size="row"
                            onClick={() => onInsert(column.name)}
                            data-attr="data-quality-check-output-column"
                        >
                            <code className="min-w-0 truncate">{column.name}</code>
                            {column.type && <Badge className="ms-auto">{column.type}</Badge>}
                        </Button>
                    ))}
                </div>
            )}
        </div>
    )
}

function PreviewRows({ preview }: { preview: CustomSqlPreview }): JSX.Element {
    const truncated =
        preview.rows.length === PREVIEW_ROW_LIMIT && (preview.hasMore || preview.rowCount > preview.rows.length)

    return (
        <div className="flex flex-col gap-1">
            <div className="overflow-x-auto">
                <Table size="sm">
                    <TableHeader>
                        <TableRow>
                            {preview.columns.map((column, index) => (
                                <TableHead key={index}>{column}</TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {preview.rows.map((row, rowIndex) => (
                            <TableRow key={rowIndex}>
                                {preview.columns.map((_, columnIndex) => (
                                    <TableCell key={columnIndex}>{formatPreviewCell(row[columnIndex])}</TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            {truncated && (
                <Text size="xs" variant="muted" className="m-0">
                    Showing the first 10 rows.
                </Text>
            )}
        </div>
    )
}

function PreviewResult(): JSX.Element | null {
    const {
        customSqlPreview,
        customSqlPreviewError,
        customSqlPreviewLoading,
        customSqlPreviewStale,
        customSqlPreviewVerdict,
    } = useValues(dataQualityCheckEditorLogic)

    if (customSqlPreviewError) {
        return <QuillCheckCallout tone="destructive">{customSqlPreviewError}</QuillCheckCallout>
    }
    if (customSqlPreviewLoading || !customSqlPreview || !customSqlPreviewVerdict) {
        return null
    }
    const atLeast = customSqlPreview.hasMore ? 'at least ' : ''

    return (
        <div className={cn('flex flex-col gap-2', customSqlPreviewStale && 'opacity-60')}>
            {customSqlPreview.warnings.length > 0 && (
                <QuillCheckCallout
                    tone="warning"
                    details={
                        <ul className="m-0 list-disc pl-5 text-xs">
                            {customSqlPreview.warnings.map((warning, index) => (
                                <li key={index}>{warning.message}</li>
                            ))}
                        </ul>
                    }
                >
                    This result may be incomplete or out of date:
                </QuillCheckCallout>
            )}
            {customSqlPreviewVerdict === 'pass' ? (
                <QuillCheckCallout tone="success">The query returned no rows. This check would pass.</QuillCheckCallout>
            ) : (
                <>
                    <QuillCheckCallout tone="warning">
                        {`The query returned ${atLeast}${customSqlPreview.rowCount} rows. This check would fail with ${atLeast}${customSqlPreview.rowCount} failures.`}
                    </QuillCheckCallout>
                    <PreviewRows preview={customSqlPreview} />
                </>
            )}
        </div>
    )
}

export function QuillCustomSqlField(): JSX.Element {
    const { customSqlEditorError, customSqlPreviewLoading, customSqlPreviewStale, isMetricSubject } =
        useValues(dataQualityCheckEditorLogic)
    const { runCustomSqlPreview } = useActions(dataQualityCheckEditorLogic)
    const editorRef = useRef<CodeEditorInstance | null>(null)

    return (
        <QuillCheckFormField
            name="customSql"
            label="Query"
            description={
                isMetricSubject
                    ? 'Query the saved metric output through {metric} exactly once. Return one row per failure; no rows means the check passes. Save the check, then run it to see the result.'
                    : 'Return one row per failure. The check passes when the query returns nothing.'
            }
        >
            {({ value, onChange }) => (
                <div className="flex flex-col gap-2">
                    <CustomSqlCodeEditor value={value} onChange={onChange} editorRef={editorRef} />
                    <AvailableColumns onInsert={(columnName) => insertOutputColumn(editorRef.current, columnName)} />
                    {!isMetricSubject && (
                        <div className="flex flex-col items-end gap-1">
                            <Button
                                variant="outline"
                                loading={customSqlPreviewLoading}
                                disabledReason={
                                    !value?.trim()
                                        ? 'Write a query before testing it.'
                                        : (customSqlEditorError ?? undefined)
                                }
                                onClick={() => runCustomSqlPreview(undefined)}
                                data-attr="data-quality-check-test-query"
                            >
                                Test query
                            </Button>
                            {customSqlPreviewStale && (
                                <Text size="xs" variant="muted" className="m-0">
                                    The query changed since the last test.
                                </Text>
                            )}
                        </div>
                    )}
                    <PreviewResult />
                </div>
            )}
        </QuillCheckFormField>
    )
}
