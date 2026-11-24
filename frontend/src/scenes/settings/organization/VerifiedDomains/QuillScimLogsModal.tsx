import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Heading,
    Input,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'

import { SCIMRequestLogApi } from '~/generated/core/api.schemas'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

const PAGE_SIZE = 20

const STATUS_FILTERS = [
    { value: 'all', label: 'All' },
    { value: 'success', label: 'Success' },
    { value: '4xx', label: '4xx' },
    { value: '5xx', label: '5xx' },
] as const

type StatusFilter = (typeof STATUS_FILTERS)[number]['value']

function statusBadgeVariant(status: number): 'success' | 'warning' | 'destructive' | 'default' {
    if (status >= 200 && status < 300) {
        return 'success'
    }
    if (status >= 400 && status < 500) {
        return 'warning'
    }
    if (status >= 500) {
        return 'destructive'
    }
    return 'default'
}

function JsonSection({ title, value }: { title: string; value: unknown }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Heading size="sm" render={<h4 className="m-0" />}>
                {title}
            </Heading>
            <CodeSnippet language={Language.JSON} wrap>
                {JSON.stringify(value, null, 2)}
            </CodeSnippet>
        </div>
    )
}

const columns: ColumnDef<SCIMRequestLogApi>[] = [
    {
        id: 'created_at',
        header: 'Time',
        cell: ({ row }) => new Date(row.original.created_at).toLocaleString(),
    },
    { id: 'request_method', header: 'Method', cell: ({ row }) => row.original.request_method },
    { id: 'request_path', header: 'Path', meta: { expand: true }, cell: ({ row }) => row.original.request_path },
    {
        id: 'response_status',
        header: 'Status',
        cell: ({ row }) => (
            <Badge variant={statusBadgeVariant(row.original.response_status)}>{row.original.response_status}</Badge>
        ),
    },
    { id: 'identity_provider', header: 'IdP', cell: ({ row }) => row.original.identity_provider },
    {
        id: 'duration_ms',
        header: 'Duration',
        cell: ({ row }) => (row.original.duration_ms !== null ? `${row.original.duration_ms}ms` : '–'),
    },
]

export function QuillScimLogsModal({ emptyText, onClose }: { emptyText: string; onClose: () => void }): JSX.Element {
    const { scimLogsModalId, scimLogs, scimLogsLoading, scimLogsStatusFilter, scimLogsSearch, scimLogsPage } =
        useValues(verifiedDomainsLogic)
    const { setScimLogsStatusFilter, setScimLogsSearch, setScimLogsPage, reloadScimLogs } =
        useActions(verifiedDomainsLogic)
    const [selectedLogId, setSelectedLogId] = useState<string | null>(null)

    const logs = scimLogs?.results ?? []
    const selectedLog = logs.find((log) => log.id === selectedLogId)

    return (
        <Dialog open={!!scimLogsModalId} onOpenChange={(open) => !open && onClose()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>SCIM request logs</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <ToggleGroup
                                variant="outline"
                                aria-label="Status"
                                value={[scimLogsStatusFilter]}
                                onValueChange={(next: string[]) => {
                                    const picked = next[0] as StatusFilter | undefined
                                    if (picked) {
                                        setScimLogsStatusFilter(picked)
                                    }
                                }}
                            >
                                {STATUS_FILTERS.map((option) => (
                                    <ToggleGroupItem key={option.value} value={option.value}>
                                        {option.label}
                                    </ToggleGroupItem>
                                ))}
                            </ToggleGroup>
                            <Input
                                type="search"
                                size="sm"
                                aria-label="Search by path or email"
                                placeholder="Search by path or email..."
                                value={scimLogsSearch}
                                onChange={(event) => setScimLogsSearch(event.target.value)}
                                className="max-w-60"
                            />
                            <Button
                                variant="outline"
                                className="ms-auto"
                                onClick={reloadScimLogs}
                                loading={scimLogsLoading}
                            >
                                <IconRefresh />
                                Refresh
                            </Button>
                        </div>

                        {scimLogsLoading && !scimLogs ? (
                            <Skeleton className="h-40 w-full" />
                        ) : (
                            <DataTable
                                columns={columns}
                                data={logs}
                                getRowId={(log) => log.id}
                                fullWidth
                                size="sm"
                                onRowClick={(log) => setSelectedLogId(log.id === selectedLogId ? null : log.id)}
                                rowClassName={(log) => (log.id === selectedLogId ? 'bg-fill-selected' : undefined)}
                                empty={
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        {emptyText}
                                    </Text>
                                }
                            />
                        )}

                        {scimLogs && scimLogs.count > PAGE_SIZE && (
                            <QuillTablePagination
                                currentPage={scimLogsPage}
                                pageCount={Math.ceil(scimLogs.count / PAGE_SIZE)}
                                pageSize={PAGE_SIZE}
                                total={scimLogs.count}
                                onPageChange={setScimLogsPage}
                            />
                        )}

                        {selectedLog && (
                            <div className="flex flex-col gap-4">
                                <JsonSection title="Request headers" value={selectedLog.request_headers} />
                                {selectedLog.request_body ? (
                                    <JsonSection title="Request body" value={selectedLog.request_body} />
                                ) : null}
                                {selectedLog.response_body ? (
                                    <JsonSection title="Response body" value={selectedLog.response_body} />
                                ) : null}
                            </div>
                        )}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
