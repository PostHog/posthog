import { IconCalendar, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTag,
    LemonTagProps,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils'

import { LogEntryLevel } from '~/types'

import { ALL_LOG_LEVELS, GroupedLogEntry, LOG_VIEWER_LIMIT, logsViewerLogic } from './logsViewerLogic'
import { LogsViewerLogicProps } from './logsViewerLogic'

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
}

/**
 * NOTE: There is a loose attempt to keeep this generic so we can use it as an abstract log component in the future.
 */
export function LogsViewer({ renderColumns = (c) => c, ...props }: LogsViewerProps): JSX.Element {
    const logic = logsViewerLogic(props)

    const { logs, logsLoading, hiddenLogs, hiddenLogsLoading, isThereMoreToLoad, expandedRows, filters } =
        useValues(logic)
    const { revealHiddenLogs, loadMoreLogs, setFilters, setRowExpanded } = useActions(logic)

    return (
        <div className="flex-1 deprecated-space-y-2 ph-no-capture">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    className="flex-1 min-w-120"
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
                <div className="flex items-center gap-2">
                    <LemonDropdown
                        closeOnClickInside={false}
                        matchWidth={false}
                        placement="right-end"
                        overlay={
                            <div className="deprecated-space-y-2 overflow-hidden max-w-100">
                                {ALL_LOG_LEVELS.map((level) => {
                                    return (
                                        <LemonButton
                                            key={level}
                                            fullWidth
                                            icon={
                                                <LemonCheckbox
                                                    checked={filters.levels.includes(level)}
                                                    className="pointer-events-none"
                                                />
                                            }
                                            onClick={() => {
                                                setFilters({
                                                    levels: filters.levels.includes(level)
                                                        ? filters.levels.filter((t) => t != level)
                                                        : [...filters.levels, level],
                                                })
                                            }}
                                        >
                                            {level}
                                        </LemonButton>
                                    )
                                })}
                            </div>
                        }
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            tooltip="Filtering for any log groups containing any of the selected levels"
                        >
                            {filters.levels.map((level) => level).join(', ')}
                        </LemonButton>
                    </LemonDropdown>

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
                </div>
            </div>
            <LemonButton
                onClick={revealHiddenLogs}
                loading={hiddenLogsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!hiddenLogs.length ? "There's nothing to load" : undefined}
            >
                {hiddenLogs.length
                    ? `Show ${pluralize(hiddenLogs.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>

            <LemonTable
                dataSource={logs}
                loading={logsLoading}
                className="ph-no-capture"
                rowKey={(record) => record.instanceId}
                columns={renderColumns([
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'maxTimestamp',
                        width: 0,
                        sorter: (a: GroupedLogEntry, b: GroupedLogEntry) =>
                            a.maxTimestamp.unix() - b.maxTimestamp.unix(),
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
                                        {lastEntry.message}
                                        {entries.length > 1 && (
                                            <>
                                                <br />
                                                <span className="text-xs text-muted-alt">
                                                    + {entries.length - 1} more
                                                </span>
                                            </>
                                        )}
                                    </Link>
                                </code>
                            )
                        },
                    },
                ])}
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
                                        render: (_, { level }) => (
                                            <LemonTag type={tagTypeForLevel(level)}>{level.toUpperCase()}</LemonTag>
                                        ),
                                    },
                                    {
                                        title: 'Message',
                                        key: 'message',
                                        dataIndex: 'message',
                                        render: (_, { message }) => (
                                            <code className="whitespace-pre-wrap">{message}</code>
                                        ),
                                    },
                                ]}
                            />
                        )
                    },
                }}
            />
            {!!logs.length && (
                <LemonButton
                    onClick={loadMoreLogs}
                    loading={logsLoading}
                    type="secondary"
                    fullWidth
                    center
                    disabledReason={!isThereMoreToLoad ? "There's nothing more to load" : undefined}
                >
                    {isThereMoreToLoad ? `Load up to ${LOG_VIEWER_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}

            <div className="mb-8" />
        </div>
    )
}
