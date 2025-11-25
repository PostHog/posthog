import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { humanFriendlyNumber } from '~/lib/utils'

import { queryLogTableLogic } from './queryLogTableLogic'

const removeQueryIndentation = (text: string): string => {
    const lines = text.split('\n')

    while (lines.length && lines[0].trim() === '') {
        lines.shift()
    }

    while (lines.length && lines[lines.length - 1].trim() === '') {
        lines.pop()
    }

    const nonEmptyLines = lines.filter((line) => line.trim() !== '')
    const minIndent = nonEmptyLines.length
        ? Math.min(
              ...nonEmptyLines.map((line) => {
                  const match = line.match(/^[ \t]*/)
                  return match ? match[0].length : 0
              })
          )
        : 0

    const trimmedLines =
        minIndent > 0
            ? lines.map((line) => {
                  const indentRegex = new RegExp(`^[ \\t]{0,${minIndent}}`)
                  return line.replace(indentRegex, '')
              })
            : lines

    return trimmedLines.join('\n')
}

interface QueryLogTableProps {
    queryKey: string
    onLoadQuery: (query: string) => void
}

export function QueryLogTable({ queryKey, onLoadQuery }: QueryLogTableProps): JSX.Element {
    const logic = queryLogTableLogic({ key: queryKey })
    const { queryLogs, queryLogsLoading, moreQueryLogsLoading, hasMore } = useValues(logic)
    const { loadQueryLogs, loadMoreQueryLogs } = useActions(logic)

    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <span className="text-sm text-muted">
                    Showing queries from the past 7 days for the current user (100 per page)
                </span>
                <LemonButton type="primary" size="small" onClick={loadQueryLogs} loading={queryLogsLoading}>
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                dataSource={queryLogs}
                loading={queryLogsLoading}
                columns={[
                    {
                        title: '',
                        key: 'load',
                        width: 40,
                        render: (_dataValue, record) => (
                            <Tooltip title="Load query into editor">
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconArrowRight />}
                                    onClick={() => {
                                        const hogqlQuery = {
                                            kind: 'HogQLQuery',
                                            query: record.query,
                                        }
                                        onLoadQuery(JSON.stringify(hogqlQuery, null, 2))
                                    }}
                                />
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Query ID',
                        key: 'query_id',
                        dataIndex: 'query_id',
                        width: 200,
                        render: (value) => {
                            const text = value !== null && value !== undefined ? String(value) : ''
                            return text ? (
                                <CopyToClipboardInline
                                    explicitValue={text}
                                    description="query ID"
                                    tooltipMessage="Copy query ID"
                                    iconSize="xsmall"
                                    className="font-mono text-xs truncate"
                                >
                                    {text}
                                </CopyToClipboardInline>
                            ) : null
                        },
                    },
                    {
                        title: 'Time',
                        key: 'query_start_time',
                        dataIndex: 'query_start_time',
                        width: 180,
                        render: (value) => (value ? new Date(String(value)).toLocaleString() : ''),
                    },
                    {
                        title: 'Duration',
                        key: 'query_duration_ms',
                        dataIndex: 'query_duration_ms',
                        width: 100,
                        render: (value) => `${value}ms`,
                        sorter: (a, b) => a.query_duration_ms - b.query_duration_ms,
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        dataIndex: 'status',
                        width: 120,
                        render: (value, record) => (
                            <LemonTag type={record.exception_code === 0 ? 'success' : 'danger'}>{value}</LemonTag>
                        ),
                    },
                    {
                        title: 'Rows Read',
                        key: 'read_rows',
                        dataIndex: 'read_rows',
                        width: 100,
                        render: (value) => humanFriendlyNumber(value as number),
                        sorter: (a, b) => a.read_rows - b.read_rows,
                    },
                    {
                        title: 'Bytes Read',
                        key: 'read_bytes',
                        dataIndex: 'read_bytes',
                        width: 100,
                        render: (value) => humanFriendlyNumber(value as number),
                        sorter: (a, b) => a.read_bytes - b.read_bytes,
                    },
                    {
                        title: 'Result Rows',
                        key: 'result_rows',
                        dataIndex: 'result_rows',
                        width: 100,
                        render: (value) => humanFriendlyNumber(value as number),
                        sorter: (a, b) => a.result_rows - b.result_rows,
                    },
                    {
                        title: 'Query',
                        key: 'query',
                        dataIndex: 'query',
                        render: (value) => {
                            const text = value !== null && value !== undefined ? String(value) : ''
                            const normalizedText = text ? removeQueryIndentation(text) : ''
                            return normalizedText ? (
                                <CopyToClipboardInline
                                    explicitValue={normalizedText}
                                    description="query"
                                    tooltipMessage="Copy query"
                                    iconSize="xsmall"
                                    className="font-mono text-xs whitespace-pre max-w-300"
                                >
                                    {normalizedText}
                                </CopyToClipboardInline>
                            ) : null
                        },
                    },
                ]}
            />
            {hasMore && (
                <div className="flex justify-center mt-4">
                    <LemonButton type="secondary" onClick={loadMoreQueryLogs} loading={moreQueryLogsLoading} center>
                        Load more
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
