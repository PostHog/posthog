import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'
import { LogLevelDisplay } from 'scenes/pipeline/utils'

import { ExternalDataJob, LogEntry } from '~/types'

import { schemaLogLogic } from './schemaLogLogic'

const columns: LemonTableColumns<LogEntry> = [
    {
        title: 'Timestamp',
        key: 'timestamp',
        dataIndex: 'timestamp',
        width: 1,
        render: (_, entry) => dayjs(entry.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
    },
    {
        title: 'Level',
        key: 'level',
        dataIndex: 'level',
        width: 1,
        render: (_, entry) => LogLevelDisplay(entry.level),
    },
    {
        title: 'Run ID',
        key: 'run_id',
        dataIndex: 'instance_id',
        width: 1,
        render: (_, entry) => entry.instance_id,
    },
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        width: 6,
    },
]

interface LogsTableProps {
    job: ExternalDataJob
}

export const LogsView = ({ job }: LogsTableProps): JSX.Element => {
    const logic = schemaLogLogic({ job })
    const { logs, logsLoading, logsBackground, isThereMoreToLoad } = useValues(logic)
    const { revealBackground, loadSchemaLogsMore } = useActions(logic)

    return (
        <div className="ph-no-capture space-y-2 flex-1">
            <LemonButton
                onClick={revealBackground}
                loading={logsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!logsBackground.length ? "There's nothing to load" : undefined}
            >
                {logsBackground.length
                    ? `Load ${pluralize(logsBackground.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>
            <LemonTable
                dataSource={logs}
                columns={columns}
                loading={logsLoading}
                className="ph-no-capture"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!logs.length && (
                <LemonButton
                    onClick={loadSchemaLogsMore}
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
