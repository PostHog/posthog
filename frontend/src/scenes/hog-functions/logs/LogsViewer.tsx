import { useActions, useValues } from 'kea'

import { IconCalendar, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTag,
    LemonTagProps,
    Link,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh, IconWithCount } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'

import { LogEntryLevel } from '~/types'

import { LogLevelsPicker } from './LogLevelsPicker'
import { GroupedLogEntry, LOG_VIEWER_LIMIT, LogEntry, LogsViewerLogicProps, logsViewerLogic } from './logsViewerLogic'

export const tagTypeForLevel = (level: LogEntryLevel): LemonTagProps['type'] => {
    switch (level.toLowerCase()) {
        case 'debug':
            return 'muted'
        case 'log':
        case 'info':
            return 'default'
        case 'warning':
        case 'warn':
            return 'warning'
        case 'error':
            return 'danger'
        default:
            return 'default'
    }
}

export type LogsViewerProps = LogsViewerLogicProps & {
    renderColumns?: (
        columns: LemonTableColumn<GroupedLogEntry, keyof GroupedLogEntry | undefined>[]
    ) => LemonTableColumn<GroupedLogEntry, keyof GroupedLogEntry | undefined>[]
    renderMessage?: (message: string) => JSX.Element | string
}

/**
 * NOTE: There is a loose attempt to keeep this generic so we can use it as an abstract log component in the future.
 */
export function LogsViewer({
    renderColumns = (c) => c,
    renderMessage = (m) => m,
    ...props
}: LogsViewerProps): JSX.Element {
    const logic = logsViewerLogic(props)

    const { logs, logsLoading, hiddenLogs, hiddenLogsLoading, isThereMoreToLoad, expandedRows, filters, isGrouped } =
        useValues(logic)
    const { revealHiddenLogs, loadMoreLogs, setFilters, setRowExpanded, setIsGrouped } = useActions(logic)

    const logColumns: LemonTableColumn<LogEntry, keyof LogEntry | undefined>[] = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            dataIndex: 'timestamp',
            render: (_, { timestamp }) => <TZLabel time={timestamp} />,
        },
        {
            title: 'Level',
            key: 'level',
            dataIndex: 'level',
            render: (_, { level }) => <LemonTag type={tagTypeForLevel(level)}>{level.toUpperCase()}</LemonTag>,
        },
        {
            title: 'Message',
            key: 'message',
            dataIndex: 'message',
            render: (_, { message }) => <code className="whitespace-pre-wrap">{renderMessage(message)}</code>,
        },
    ]

    const groupedLogColumns: LemonTableColumn<GroupedLogEntry, keyof GroupedLogEntry | undefined>[] = renderColumns([
        {
            title: 'Timestamp',
            key: 'timestamp',
            dataIndex: 'maxTimestamp',
            width: 0,
            sorter: (a: GroupedLogEntry, b: GroupedLogEntry) => a.maxTimestamp.unix() - b.maxTimestamp.unix(),
            render: (_, { maxTimestamp }) => <TZLabel time={maxTimestamp} />,
        },
        {
            width: 0,
            title: 'Invocation',
            dataIndex: 'instanceId',
            key: 'instanceId',
            render: (_, { instanceId }) => (
                <code className="whitespace-nowrap">
                    <Link
                        className="font-semibold"
                        subtle
                        onClick={() => {
                            setRowExpanded(instanceId, !expandedRows[instanceId])
                        }}
                    >
                        {instanceId}
                    </Link>
                </code>
            ),
        },
        {
            key: 'logLevel',
            dataIndex: 'logLevel',
            width: 0,
            render: (_, { instanceId, logLevel }) => {
                return (
                    <Link
                        subtle
                        className="flex items-center gap-2"
                        onClick={() => {
                            setRowExpanded(instanceId, !expandedRows[instanceId])
                        }}
                    >
                        <LemonTag type={tagTypeForLevel(logLevel)}>{logLevel.toUpperCase()}</LemonTag>
                    </Link>
                )
            },
        },
        {
            title: 'Last message',
            key: 'entries',
            dataIndex: 'entries',
            render: (_, { instanceId, entries }) => {
                const lastEntry = entries[entries.length - 1]
                return (
                    <code className="whitespace-pre-wrap">
                        <Link
                            subtle
                            onClick={() => {
                                setRowExpanded(instanceId, !expandedRows[instanceId])
                            }}
                        >
                            {renderMessage(lastEntry.message)}
                            {entries.length > 1 && (
                                <>
                                    <br />
                                    <span className="text-xs text-muted-alt">+ {entries.length - 1} more</span>
                                </>
                            )}
                        </Link>
                    </code>
                )
            },
        },
    ])

    const footer = (
        <LemonButton
            onClick={loadMoreLogs}
            loading={logsLoading}
            fullWidth
            center
            disabledReason={!isThereMoreToLoad ? "There's nothing more to load" : undefined}
        >
            {isThereMoreToLoad ? `Load up to ${LOG_VIEWER_LIMIT} older entries` : 'No older entries'}
        </LemonButton>
    )

    return (
        <div className="flex-1 deprecated-space-y-2 ph-no-capture flex flex-col overflow-hidden">
            <div className="flex flex-wrap flex-row-reverse items-center gap-2">
                <div className="flex items-center gap-2 flex-1 min-w-100">
                    <LemonInput
                        type="search"
                        placeholder="Search for messages containing…"
                        fullWidth
                        onChange={(value) => setFilters({ search: value })}
                        allowClear
                        prefix={
                            <>
                                <IconSearch />
                            </>
                        }
                    />
                    <LemonButton
                        onClick={revealHiddenLogs}
                        loading={hiddenLogsLoading}
                        type="secondary"
                        icon={
                            <IconWithCount count={hiddenLogs.length}>
                                <IconRefresh />
                            </IconWithCount>
                        }
                        disabledReason={!hiddenLogs.length ? "There's nothing to load" : undefined}
                        tooltip={
                            hiddenLogs.length
                                ? `Show ${pluralize(hiddenLogs.length, 'newer entry', 'newer entries')}`
                                : 'No new entries'
                        }
                    />
                </div>
                <div className="flex items-center gap-2">
                    <LogLevelsPicker value={filters.levels} onChange={(levels) => setFilters({ levels })} />

                    <DateFilter
                        dateTo={filters.date_to}
                        dateFrom={filters.date_from}
                        onChange={(from, to) => setFilters({ date_from: from || undefined, date_to: to || undefined })}
                        allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar /> {key}
                            </>
                        )}
                    />

                    {typeof props.groupByInstanceId !== 'boolean' && (
                        <LemonSelect
                            value={isGrouped}
                            onChange={(checked) => setIsGrouped(checked)}
                            options={[
                                { label: 'Grouped', value: true },
                                { label: 'Ungrouped', value: false },
                            ]}
                        />
                    )}
                </div>
            </div>

            {isGrouped ? (
                <LemonTable
                    key="grouped"
                    dataSource={logs}
                    loading={logsLoading}
                    className="ph-no-capture overflow-y-auto"
                    rowKey={(record) => record.instanceId}
                    footer={footer}
                    columns={groupedLogColumns}
                    expandable={{
                        noIndent: true,
                        isRowExpanded: (record) => expandedRows[record.instanceId] ?? false,
                        onRowExpand: (record) => setRowExpanded(record.instanceId, true),
                        onRowCollapse: (record) => setRowExpanded(record.instanceId, false),
                        expandedRowRender: (record) => {
                            return (
                                <LemonTable
                                    embedded
                                    dataSource={record.entries}
                                    columns={[
                                        {
                                            key: 'spacer',
                                            width: 0,
                                            render: () => <div className="w-6" />,
                                        },
                                        ...logColumns,
                                    ]}
                                />
                            )
                        },
                    }}
                />
            ) : (
                <LemonTable
                    key="ungrouped"
                    dataSource={logs.flatMap((log) => log.entries)}
                    loading={logsLoading}
                    className="ph-no-capture overflow-y-auto"
                    rowKey={(record, index) => `${record.timestamp.toISOString()}-${index}`}
                    columns={logColumns}
                    footer={footer}
                />
            )}

            <div className="mb-8" />
        </div>
    )
}
