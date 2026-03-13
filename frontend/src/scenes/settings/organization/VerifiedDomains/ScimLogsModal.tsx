import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'

import { SCIMRequestLogType } from '~/types'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

function statusTagType(status: number): LemonTagType {
    if (status >= 200 && status < 300) {
        return 'success'
    }
    if (status >= 400 && status < 500) {
        return 'warning'
    }
    if (status >= 500) {
        return 'danger'
    }
    return 'default'
}

function LogDetailExpanded({ log }: { log: SCIMRequestLogType }): JSX.Element {
    return (
        <div className="space-y-4 p-4">
            <div>
                <h4 className="font-semibold mb-1">Request headers</h4>
                <CodeSnippet language={Language.JSON} wrap>
                    {JSON.stringify(log.request_headers, null, 2)}
                </CodeSnippet>
            </div>
            {log.request_body ? (
                <div>
                    <h4 className="font-semibold mb-1">Request body</h4>
                    <CodeSnippet language={Language.JSON} wrap>
                        {JSON.stringify(log.request_body, null, 2)}
                    </CodeSnippet>
                </div>
            ) : null}
            {log.response_body ? (
                <div>
                    <h4 className="font-semibold mb-1">Response body</h4>
                    <CodeSnippet language={Language.JSON} wrap>
                        {JSON.stringify(log.response_body, null, 2)}
                    </CodeSnippet>
                </div>
            ) : null}
        </div>
    )
}

export function ScimLogsModal(): JSX.Element {
    const { scimLogsModalId, scimLogs, scimLogsLoading, scimLogsStatusFilter, scimLogsSearch, scimLogsPage } =
        useValues(verifiedDomainsLogic)
    const { setScimLogsModalId, setScimLogsStatusFilter, setScimLogsSearch, setScimLogsPage } =
        useActions(verifiedDomainsLogic)

    const columns: LemonTableColumns<SCIMRequestLogType> = [
        {
            key: 'created_at',
            title: 'Time',
            render: (_, { created_at }) => new Date(created_at).toLocaleString(),
        },
        {
            key: 'request_method',
            title: 'Method',
            dataIndex: 'request_method',
        },
        {
            key: 'request_path',
            title: 'Path',
            dataIndex: 'request_path',
        },
        {
            key: 'response_status',
            title: 'Status',
            render: (_, { response_status }) => (
                <LemonTag type={statusTagType(response_status)}>{response_status}</LemonTag>
            ),
        },
        {
            key: 'identity_provider',
            title: 'IdP',
            dataIndex: 'identity_provider',
        },
        {
            key: 'duration_ms',
            title: 'Duration',
            render: (_, { duration_ms }) => (duration_ms !== null ? `${duration_ms}ms` : '–'),
        },
    ]

    const pagination: PaginationManual | undefined = scimLogs
        ? {
              controlled: true,
              pageSize: 20,
              currentPage: scimLogsPage,
              entryCount: scimLogs.count,
              onForward: scimLogs.next ? () => setScimLogsPage(scimLogsPage + 1) : undefined,
              onBackward: scimLogs.previous ? () => setScimLogsPage(scimLogsPage - 1) : undefined,
          }
        : undefined

    const handleClose = (): void => setScimLogsModalId(null)

    return (
        <LemonModal onClose={handleClose} isOpen={!!scimLogsModalId} title="SCIM request logs" width={960}>
            <div className="space-y-4">
                <div className="flex items-center gap-2">
                    <LemonSegmentedButton
                        value={scimLogsStatusFilter}
                        onChange={(value) => setScimLogsStatusFilter(value)}
                        options={[
                            { value: 'all', label: 'All' },
                            { value: 'success', label: 'Success' },
                            { value: '4xx', label: '4xx' },
                            { value: '5xx', label: '5xx' },
                        ]}
                        size="small"
                    />
                    <LemonInput
                        type="search"
                        placeholder="Search by path or email..."
                        value={scimLogsSearch}
                        onChange={setScimLogsSearch}
                        className="max-w-60"
                        size="small"
                    />
                </div>

                <LemonTable
                    dataSource={scimLogs?.results ?? []}
                    columns={columns}
                    loading={scimLogsLoading}
                    rowKey="id"
                    pagination={pagination}
                    expandable={{
                        expandedRowRender: (log) => <LogDetailExpanded log={log} />,
                    }}
                    emptyState={
                        scimLogsStatusFilter !== 'all' || scimLogsSearch
                            ? 'No SCIM requests match the current filters.'
                            : 'No SCIM requests logged yet for this domain.'
                    }
                />
            </div>
        </LemonModal>
    )
}
