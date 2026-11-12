import { useValues } from 'kea'

import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'

import type { CustomPropertySyncRunApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { runLogsWindow } from './customPropertyTypes'

export interface CustomPropertySyncRunLogsProps {
    run: CustomPropertySyncRunApi
    logSourceId: string
}

export function CustomPropertySyncRunLogs({ run, logSourceId }: CustomPropertySyncRunLogsProps): JSX.Element {
    const { timezone } = useValues(teamLogic)

    return (
        <div className="min-w-0 p-4">
            <LogsViewer
                logicKey={`warehouse_property_run:${run.id}`}
                sourceType="warehouse_property_run"
                sourceId={logSourceId}
                groupByInstanceId={false}
                hideDateFilter
                hideLevelsFilter
                hideInstanceIdColumn
                defaultAscending
                // Several runs can be expanded at once, and the viewers would share the unprefixed URL params.
                disableUrlSync
                defaultFilters={{
                    instanceId: run.workflow_run_id ?? undefined,
                    ...runLogsWindow(run, timezone),
                }}
            />
        </div>
    )
}
