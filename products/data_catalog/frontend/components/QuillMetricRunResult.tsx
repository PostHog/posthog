import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { DataCatalogMetricRunResult } from './MetricDefinition'
import { QuillMetricCodeBlock, renderQuillMetricCodeBlock } from './QuillMetricCodeBlock'
import { QuillResultCell } from './QuillResultCell'

function ResultsTable({ results }: { results: unknown }): JSX.Element {
    const rows = Array.isArray(results) ? results : []
    if (rows.length === 0) {
        return (
            <Text size="xs" variant="muted" className="m-0">
                No results.
            </Text>
        )
    }
    const first = rows[0]
    if (!first || typeof first !== 'object' || Array.isArray(first)) {
        return <QuillMetricCodeBlock code={JSON.stringify(results, null, 2)} language={Language.JSON} />
    }
    const columnKeys = Object.keys(first as Record<string, unknown>)
    return (
        <div className="overflow-x-auto">
            <Table size="sm" fullWidth>
                <TableHeader>
                    <TableRow>
                        {columnKeys.map((columnKey) => (
                            <TableHead key={columnKey}>{columnKey}</TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {(rows as Record<string, unknown>[]).map((row, rowIndex) => (
                        <TableRow key={rowIndex}>
                            {columnKeys.map((columnKey) => (
                                <TableCell key={columnKey}>
                                    <QuillResultCell value={row[columnKey]} />
                                </TableCell>
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    )
}

export function QuillMetricRunResult({ runResult }: { runResult: DataCatalogMetricRunResult }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {runResult.instructions ? (
                <LemonMarkdown disableImages renderCodeBlock={renderQuillMetricCodeBlock}>
                    {runResult.instructions}
                </LemonMarkdown>
            ) : (
                <ResultsTable results={runResult.results} />
            )}
            {runResult.compiled_query && (
                <Collapsible>
                    <CollapsibleTrigger>Compiled query</CollapsibleTrigger>
                    <CollapsibleContent>
                        <QuillMetricCodeBlock code={runResult.compiled_query} language={Language.SQL} />
                    </CollapsibleContent>
                </Collapsible>
            )}
        </div>
    )
}
