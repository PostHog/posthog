import { IconCalendar, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
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

import {
    ALL_LOG_LEVELS,
    DEFAULT_LOG_LEVELS,
    GroupedLogEntry,
    LOG_VIEWER_LIMIT,
    logsViewerLogic,
} from './logsViewerLogic'
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

    const { logs, logsLoading, backgroundLogs, isThereMoreToLoad, expandedRows, filters } = useValues(logic)
    const { revealBackground, loadMoreLogs, setFilters, setRowExpanded } = useActions(logic)

    return (
        <div className="flex-1 space-y-2 ph-no-capture">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={(value) => setFilters({ searchTerm: value })}
                allowClear
                prefix={
                    <>
                        <IconSearch />
                    </>
                }
            />
            <div className="flex items-center gap-4">
                <DateFilter
                    dateTo={filters.before}
                    dateFrom={filters.after}
                    onChange={(from, to) => setFilters({ after: from || undefined, before: to || undefined })}
                    allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                    makeLabel={(key) => (
                        <>
                            <IconCalendar /> {key}
                        </>
                    )}
                />

                <span className="mr-1">Show logs of level:</span>
                {ALL_LOG_LEVELS.map((level) => {
                    return (
                        <LemonCheckbox
                            key={level}
                            label={level}
                            checked={filters.logLevels.includes(level)}
                            onChange={(checked) => {
                                const newLogLevels = checked
                                    ? [...filters.logLevels, level]
                                    : filters.logLevels.filter((t) => t != level)
                                setFilters({ logLevels: newLogLevels.length ? newLogLevels : DEFAULT_LOG_LEVELS })
                            }}
                        />
                    )
                })}
            </div>
            <LemonButton
                onClick={revealBackground}
                loading={logsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!backgroundLogs.length ? "There's nothing to load" : undefined}
            >
                {backgroundLogs.length
                    ? `Load ${pluralize(backgroundLogs.length, 'newer entry', 'newer entries')}`
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
