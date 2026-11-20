import { useValues } from 'kea'

import { dayjsUtcToTimezone } from 'lib/dayjs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { LogEntryLevel } from '~/types'

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

export interface JobLogsViewerProps {
    jobId: string
    schemaId: string
    workflowRunId: string | null | undefined
    createdAt: string
    finishedAt: string | null | undefined
}

/** The log lines of one sync run, read from the run's table and narrowed to the run's time range. */
export function JobLogsViewer({
    jobId,
    schemaId,
    workflowRunId,
    createdAt,
    finishedAt,
}: JobLogsViewerProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    return (
        <LogsViewer
            logicKey={`external_data_jobs:${jobId}`}
            sourceType="external_data_jobs"
            sourceId={schemaId}
            groupByInstanceId={false}
            hideDateFilter={true}
            hideLevelsFilter={true}
            hideInstanceIdColumn={true}
            defaultFilters={{
                instanceId: workflowRunId ?? undefined,
                dateFrom: dayjsUtcToTimezone(createdAt, timezone).format('YYYY-MM-DD HH:mm:ss'),
                dateTo: finishedAt
                    ? dayjsUtcToTimezone(finishedAt, timezone).add(1, 'hour').format('YYYY-MM-DD HH:mm:ss')
                    : undefined,
                levels: showDebugLogs ? ['DEBUG', ...LOG_LEVELS] : LOG_LEVELS,
            }}
        />
    )
}
