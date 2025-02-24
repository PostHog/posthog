import { IconSearch } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonInput, LemonSnack, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'
import { LogLevelDisplay } from 'scenes/pipeline/utils'

import { LogEntryLevel } from '~/types'

import { ALL_LOG_LEVELS, GroupedLogEntry, hogFunctionLogsLogic, HogFunctionLogsProps } from './hogFunctionLogsLogic'

export function HogFunctionLogs({ id }: HogFunctionLogsProps): JSX.Element {
    const hogFunctionId = id.startsWith('hog-') ? id.substring(4) : id

    const logic = hogFunctionLogsLogic({ id: hogFunctionId })

    const { logs, logsLoading, backgroundLogs, isThereMoreToLoad, selectedLogLevels, instanceId } = useValues(logic)
    const { revealBackground, loadMoreLogs, setSelectedLogLevels, setSearchTerm, setInstanceId } = useActions(logic)

    return (
        <div className="flex-1 space-y-2 ph-no-capture">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
                prefix={
                    <>
                        <IconSearch />

                        {instanceId && <LemonSnack onClose={() => setInstanceId(null)}>{instanceId}</LemonSnack>}
                    </>
                }
            />
            <div className="flex items-center gap-4">
                <span className="mr-1">Show logs of level:</span>
                {ALL_LOG_LEVELS.map((level) => {
                    return (
                        <LemonCheckbox
                            key={level}
                            label={level}
                            checked={selectedLogLevels.includes(level)}
                            onChange={(checked) => {
                                const newLogLevels = checked
                                    ? [...selectedLogLevels, level]
                                    : selectedLogLevels.filter((t) => t != level)
                                setSelectedLogLevels(newLogLevels)
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
                rowKey={(record) => `${record.instanceId}:${record.timestamp}`}
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
                columns={[
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        sorter: (a: GroupedLogEntry, b: GroupedLogEntry) =>
                            dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
                        render: (timestamp: string) => <TZLabel time={timestamp} />,
                        width: 0,
                    },
                    {
                        width: 0,
                        title: 'Invocation',
                        dataIndex: 'instanceId',
                        key: 'instanceId',
                        render: (instanceId: string) => (
                            <code className="whitespace-nowrap">
                                <Link
                                    subtle
                                    onClick={() => {
                                        alert('TODO')
                                    }}
                                >
                                    {instanceId}
                                </Link>
                            </code>
                        ),
                    },
                    {
                        key: 'logs',
                        render: (_, { entries }) => {
                            return <LemonBadge.Number count={entries.length} />
                        },
                    },
                    {
                        title: 'Last message',
                        key: 'entries',
                        dataIndex: 'entries',
                        render: (entries: { message: string; level: LogEntryLevel; timestamp: string }[]) => {
                            const lastEntry = entries[entries.length - 1]
                            return <code className="whitespace-pre-wrap">{lastEntry.message}</code>
                        },
                    },
                ]}
                expandable={{
                    noIndent: true,
                    expandedRowRender: (record) => {
                        console.log(record)
                        return (
                            <LemonTable
                                embedded
                                dataSource={record.entries}
                                columns={[
                                    {
                                        title: 'Timestamp',
                                        key: 'timestamp',
                                        dataIndex: 'timestamp',
                                        render: (timestamp: string) => <TZLabel time={timestamp} />,
                                    },
                                    {
                                        title: 'Level',
                                        key: 'level',
                                        dataIndex: 'level',
                                        render: (level: LogEntryLevel) => LogLevelDisplay(level.toUpperCase()),
                                    },
                                    {
                                        title: 'Message',
                                        key: 'message',
                                        dataIndex: 'message',
                                        render: (message: string) => (
                                            <code className="whitespace-pre-wrap">{message}</code>
                                        ),
                                    },
                                ]}
                                // rowKey={(record) => `${record.instanceId}:${record.timestamp}`}
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
                    {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}
        </div>
    )
}
