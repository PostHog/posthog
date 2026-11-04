import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { QuillCheckCallout } from 'products/data_quality/frontend/QuillCheckCallout'

import { NodeDetailQueryEditor } from './NodeDetailQueryEditor'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const COLUMNS_PAGE_SIZE = 10

function ColumnsTable({ columns }: { columns: DatabaseSchemaField[] }): JSX.Element {
    const [requestedPage, setPage] = useState(0)
    const pageCount = Math.max(Math.ceil(columns.length / COLUMNS_PAGE_SIZE), 1)
    const page = Math.min(requestedPage, pageCount - 1)
    const pageColumns = columns.slice(page * COLUMNS_PAGE_SIZE, (page + 1) * COLUMNS_PAGE_SIZE)

    return (
        <div className="flex flex-col gap-2">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Name</TableHead>
                        <TableHead>Type</TableHead>
                    </TableRow>
                </TableHeader>
                {pageColumns.length === 0 ? (
                    <TableEmpty>
                        <Text size="xs" variant="muted">
                            Columns appear after the view runs.
                        </Text>
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {pageColumns.map((column) => (
                            <TableRow key={column.name}>
                                <TableCell expand className="font-mono">
                                    {column.name}
                                </TableCell>
                                <TableCell>{column.type}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
            {pageCount > 1 && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Text size="xs" variant="muted" render={<span className="tabular-nums" />}>
                        {`${page * COLUMNS_PAGE_SIZE + 1}-${page * COLUMNS_PAGE_SIZE + pageColumns.length} of ${columns.length} columns`}
                    </Text>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            disabledReason={page === 0 ? 'This is the first page' : undefined}
                            onClick={() => setPage(page - 1)}
                        >
                            Previous
                        </Button>
                        <Button
                            variant="outline"
                            disabledReason={page === pageCount - 1 ? 'This is the last page' : undefined}
                            onClick={() => setPage(page + 1)}
                        >
                            Next
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}

export function QuillNodeDetailQuery({ id }: { id: string }): JSX.Element {
    const { savedQuery, savedQueryLoading, savedQueryError, canEditQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))

    if (savedQueryLoading && !savedQuery) {
        return <Skeleton className="h-64 w-full" />
    }

    const refreshErrorCallout = (
        <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadSavedQuery }}>
            Couldn't load this model's query.
        </QuillCheckCallout>
    )

    if (savedQueryError && !savedQuery) {
        return refreshErrorCallout
    }

    const queryString = savedQuery?.query?.query
    const columns = savedQuery?.columns ?? []

    return (
        <div className="flex flex-col gap-4">
            {savedQueryError && refreshErrorCallout}
            {queryString && savedQuery && canEditQuery ? (
                <NodeDetailQueryEditor key={savedQuery.id} id={id} savedQuery={savedQuery} />
            ) : queryString ? (
                <CodeSnippet
                    language={Language.SQL}
                    className="[&_pre]:max-h-[70vh] [&_pre]:overflow-auto"
                    thing="query"
                >
                    {queryString}
                </CodeSnippet>
            ) : (
                <Text size="xs" variant="muted" className="m-0">
                    This model has no query.
                </Text>
            )}
            <Collapsible key={id}>
                <CollapsibleTrigger data-attr="node-detail-query-columns">
                    Columns ({columns.length})
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-2">
                    <ColumnsTable columns={columns} />
                </CollapsibleContent>
            </Collapsible>
        </div>
    )
}
