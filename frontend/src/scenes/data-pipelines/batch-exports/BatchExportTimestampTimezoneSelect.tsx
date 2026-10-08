import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { TimestampTimezoneChoice, batchExportHogQLQueryLogic } from './batchExportHogQLQueryLogic'

export function BatchExportTimestampTimezoneSelect(): JSX.Element {
    const formLogic = useMountedLogic(batchExportConfigFormLogic)
    const { configurationErrors } = useValues(formLogic)
    const logic = batchExportHogQLQueryLogic(formLogic.props)
    const { projectTimezone, defaultTimezone, teamConvertToProjectTimezone, timestampTimezoneChoice } = useValues(logic)
    const { setTimestampTimezone } = useActions(logic)

    return (
        <LemonField.Pure
            label="Query timezone"
            info="Sets the timezone for timestamps in the export and for date functions in the query."
            help={
                timestampTimezoneChoice === 'default' ? (
                    teamConvertToProjectTimezone === null ? (
                        'The default is the project timezone. If the default changes, this export uses the new one from its next run.'
                    ) : (
                        <>
                            This project's <code>convertToProjectTimezone</code> modifier was set to{' '}
                            <code>{String(teamConvertToProjectTimezone)}</code> through the API, so the default is{' '}
                            <span>{teamConvertToProjectTimezone ? 'the project timezone' : 'UTC'}</span>. If it changes,
                            this export uses the new default from its next run.
                        </>
                    )
                ) : undefined
            }
            error={configurationErrors.hogql_modifiers}
        >
            <LemonSelect<TimestampTimezoneChoice>
                fullWidth
                value={timestampTimezoneChoice}
                onChange={setTimestampTimezone}
                options={[
                    { value: 'default', label: `Use default (${defaultTimezone})` },
                    { value: 'utc', label: 'Always use UTC' },
                    { value: 'project_timezone', label: `Always use project timezone (${projectTimezone})` },
                ]}
                data-attr="batch-export-hogql-timestamp-timezone"
            />
        </LemonField.Pure>
    )
}
