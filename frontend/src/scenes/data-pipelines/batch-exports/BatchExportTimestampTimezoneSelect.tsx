import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { TimestampTimezoneChoice, batchExportHogQLQueryLogic } from './batchExportHogQLQueryLogic'

export function BatchExportTimestampTimezoneSelect(): JSX.Element {
    const { props: formLogicProps } = useMountedLogic(batchExportConfigFormLogic)
    const logic = batchExportHogQLQueryLogic(formLogicProps)
    const { projectTimezone, projectConvertsToProjectTimezone, timestampTimezoneChoice } = useValues(logic)
    const { setTimestampTimezone } = useActions(logic)

    return (
        <div className="flex flex-col gap-1">
            <LemonLabel>Export timestamps in</LemonLabel>
            <LemonSelect<TimestampTimezoneChoice>
                fullWidth
                value={timestampTimezoneChoice}
                onChange={setTimestampTimezone}
                options={[
                    {
                        value: 'project_setting',
                        label: `Project setting (${projectConvertsToProjectTimezone ? projectTimezone : 'UTC'})`,
                    },
                    { value: 'project_timezone', label: `Project timezone (${projectTimezone})` },
                    { value: 'utc', label: 'UTC' },
                ]}
                data-attr="batch-export-hogql-timestamp-timezone"
            />
            {timestampTimezoneChoice === 'project_setting' && (
                <p className="text-xs text-secondary mb-0">
                    Follows the project setting, so a change there applies to this export from its next run.
                </p>
            )}
        </div>
    )
}
