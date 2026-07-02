import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight, IconCopy } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { humanFriendlyNumber } from '~/lib/utils'

import { QueryLogEntry, queryLogLogic } from './queryLogLogic'

const MAX_PREVIEW_LINES = 3

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

// Queries arrive with the LIMIT the runner appended; strip it so reloading doesn't stack limits
const removeTrailingLimit = (text: string): string => {
    return text.replace(/\s*LIMIT\s+\d+\s*$/i, '')
}

function QueryPreview({ query }: { query: string }): JSX.Element {
    const [showFull, setShowFull] = useState(false)
    const lines = query.split('\n')
    const isTruncated = lines.length > MAX_PREVIEW_LINES
    const previewText = isTruncated ? lines.slice(0, MAX_PREVIEW_LINES).join('\n') + '\n…' : query

    const copyButton = (
        <LemonButton
            size="xsmall"
            icon={<IconCopy />}
            onClick={() => void copyToClipboard(query, 'query')}
            tooltip="Copy query"
            className="shrink-0 mt-0.5"
        />
    )

    if (!isTruncated) {
        return (
            <div className="flex items-start gap-1">
                <div className="font-mono text-xs whitespace-pre flex-1">{query}</div>
                {copyButton}
            </div>
        )
    }

    return (
        <Popover
            visible={showFull}
            onClickOutside={() => setShowFull(false)}
            placement="bottom-start"
            fallbackPlacements={['bottom-end', 'top-start']}
            overlay={
                <div className="p-2 min-w-160 max-w-320 max-h-120 overflow-auto">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-muted">Full query</span>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            onClick={() => void copyToClipboard(query, 'query')}
                            tooltip="Copy query"
                        />
                    </div>
                    <pre className="font-mono text-xs whitespace-pre-wrap m-0">{query}</pre>
                </div>
            }
        >
            <div className="flex items-start gap-1">
                <div
                    className="font-mono text-xs whitespace-pre cursor-pointer flex-1"
                    onMouseEnter={() => setShowFull(true)}
                    onMouseLeave={() => setShowFull(false)}
                >
                    {previewText}
                </div>
                {copyButton}
            </div>
        </Popover>
    )
}

interface QueryLogProps {
    tabId: string
    onLoadQuery: (query: string) => void
}

export function QueryLog({ tabId, onLoadQuery }: QueryLogProps): JSX.Element {
    const logic = queryLogLogic({ tabId })
    const { queryLog, queryLogLoading, moreQueryLogLoading, hasMore } = useValues(logic)
    const { loadQueryLog, loadMoreQueryLog } = useActions(logic)

    return (
        <div className="space-y-2">
            <div className="flex justify-between items-center">
                <span className="text-sm text-muted">Queries you ran in the SQL editor over the last 7 days</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={loadQueryLog}
                    loading={queryLogLoading}
                    data-attr="sql-editor-query-log-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                dataSource={queryLog}
                loading={queryLogLoading}
                rowKey={(record) => record.query_id}
                emptyState="No queries run in the SQL editor in the last 7 days"
                columns={[
                    {
                        title: '',
                        key: 'load',
                        width: 40,
                        render: (_, record: QueryLogEntry) => (
                            <Tooltip title="Load query into editor">
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconArrowRight />}
                                    data-attr="sql-editor-query-log-load"
                                    onClick={() => {
                                        onLoadQuery(removeTrailingLimit(removeQueryIndentation(record.query || '')))
                                    }}
                                />
                            </Tooltip>
                        ),
                    },
                    {
                        title: 'Query',
                        key: 'query',
                        dataIndex: 'query',
                        sorter: (a, b) => (a.query || '').localeCompare(b.query || ''),
                        render: (value) => {
                            const text = value !== null && value !== undefined ? String(value) : ''
                            const normalizedText = text ? removeQueryIndentation(text) : ''
                            return normalizedText ? <QueryPreview query={normalizedText} /> : null
                        },
                    },
                    {
                        title: 'Time',
                        key: 'query_start_time',
                        dataIndex: 'query_start_time',
                        width: 180,
                        sorter: (a, b) =>
                            new Date(a.query_start_time).getTime() - new Date(b.query_start_time).getTime(),
                        render: (value) => (value ? <TZLabel time={String(value)} /> : null),
                    },
                    {
                        title: 'Result rows',
                        key: 'result_rows',
                        dataIndex: 'result_rows',
                        width: 100,
                        sorter: (a, b) => a.result_rows - b.result_rows,
                        render: (value) => humanFriendlyNumber(value as number),
                    },
                    {
                        title: 'Duration',
                        key: 'query_duration_ms',
                        dataIndex: 'query_duration_ms',
                        width: 100,
                        sorter: (a, b) => a.query_duration_ms - b.query_duration_ms,
                        render: (value) => `${humanFriendlyNumber(value as number)} ms`,
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        dataIndex: 'status',
                        width: 120,
                        sorter: (a, b) => (a.status || '').localeCompare(b.status || ''),
                        render: (value, record) => (
                            <LemonTag type={record.exception_code === 0 ? 'success' : 'danger'}>{value}</LemonTag>
                        ),
                    },
                ]}
            />
            {hasMore && (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={loadMoreQueryLog}
                        loading={moreQueryLogLoading}
                        data-attr="sql-editor-query-log-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
