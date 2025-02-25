import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils'
import { useMemo } from 'react'

import { hogFunctionLogsLogic } from './hogFunctionLogsLogic'
import { LogsViewer } from './LogsViewer'
import { GroupedLogEntry, LogsViewerLogicProps } from './logsViewerLogic'

const eventIdMatchers = [/Event: ([A-Za-z0-9-]+)/, /\/events\/([A-Za-z0-9-]+)\//]

export function HogFunctionLogs(props: { hogFunctionId: string }): JSX.Element {
    return (
        <LogsViewer
            sourceType="hog_function"
            sourceId={props.hogFunctionId}
            renderColumns={(columns) => {
                // Add in custom columns for handling retries
                const newColumns: LemonTableColumns<GroupedLogEntry> = [
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: (_, record) => (
                            <HogFunctionLogsStatus record={record} hogFunctionId={props.hogFunctionId} />
                        ),
                    },
                    ...columns.filter((column) => column.key !== 'logLevel'),
                ]

                return newColumns
            }}
        />
    )
}

type HogFunctionLogsStatus = 'success' | 'failure' | 'running'

function HogFunctionLogsStatus({
    record,
    hogFunctionId,
}: {
    record: GroupedLogEntry
    hogFunctionId: string
}): JSX.Element {
    const logicProps: LogsViewerLogicProps = {
        sourceType: 'hog_function',
        sourceId: hogFunctionId,
    }

    const { retries } = useValues(hogFunctionLogsLogic(logicProps))
    const { retryInvocation } = useActions(hogFunctionLogsLogic(logicProps))

    const thisRetry = retries[record.instanceId]

    const status = useMemo<HogFunctionLogsStatus>((): HogFunctionLogsStatus => {
        if (thisRetry === 'pending') {
            return 'running'
        }

        const lastEntry = record.entries[record.entries.length - 1]

        if (lastEntry.message.includes('Function completed')) {
            return 'success'
        }

        if (lastEntry.level === 'ERROR') {
            return 'failure'
        }

        return 'running'
    }, [record, thisRetry])

    const eventId = useMemo<string | undefined>(() => {
        // TRICKY: We have the event ID in differnet logs. We will standardise this to be the invocation ID in the future.
        const entryContainingEventId = record.entries.find(
            (entry) => entry.message.includes('Function completed') || entry.message.includes('Suspending function')
        )

        if (!entryContainingEventId) {
            return undefined
        }

        for (const matcher of eventIdMatchers) {
            const match = entryContainingEventId.message.match(matcher)
            if (match) {
                return match[1]
            }
        }
    }, [record])

    return (
        <div className="flex items-center gap-2">
            <LemonTag type={status === 'success' ? 'success' : status === 'failure' ? 'danger' : 'warning'}>
                {capitalizeFirstLetter(status)}
            </LemonTag>

            <LemonMenu
                items={[
                    {
                        label: 'Retry',
                        disabledReason: !eventId ? 'Could not find the source event' : undefined,
                        onClick: () => retryInvocation(record, eventId),
                    },
                ]}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconEllipsis className="rotate-90" />}
                    loading={thisRetry === 'pending'}
                />
            </LemonMenu>
        </div>
    )
}
