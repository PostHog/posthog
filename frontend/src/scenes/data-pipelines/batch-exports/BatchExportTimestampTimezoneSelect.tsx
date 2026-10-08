import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { TimestampTimezoneChoice, batchExportHogQLQueryLogic } from './batchExportHogQLQueryLogic'

export function BatchExportTimestampTimezoneSelect(): JSX.Element {
    const formLogic = useMountedLogic(batchExportConfigFormLogic)
    const { configurationErrors } = useValues(formLogic)
    const logic = batchExportHogQLQueryLogic(formLogic.props)
    const { projectTimezone, defaultTimezone, teamConvertToProjectTimezone, timestampTimezoneChoice } = useValues(logic)
    const { setTimestampTimezone } = useActions(logic)

    let help: React.ReactNode = null
    if (timestampTimezoneChoice === 'project_timezone') {
        help = (
            <>
                If the project timezone changes in{' '}
                <Link to={urls.settings('environment-customization', 'date-and-time')} target="_blank">
                    project settings
                </Link>
                , this export uses the new timezone from its next run.
            </>
        )
    } else if (timestampTimezoneChoice === 'default' && teamConvertToProjectTimezone === null) {
        help =
            'The default is the project timezone. If the default or the project timezone changes, this export uses the new one from its next run.'
    } else if (timestampTimezoneChoice === 'default') {
        help = (
            <>
                This project's <code>convertToProjectTimezone</code> modifier was set to{' '}
                <code>{String(teamConvertToProjectTimezone)}</code> through the API, so the default is{' '}
                <span>{teamConvertToProjectTimezone ? 'the project timezone' : 'UTC'}</span>. If it changes, this export
                uses the new default from its next run.
            </>
        )
    }

    return (
        <LemonField.Pure
            label="Query timezone"
            info={
                <>
                    Sets the timezone for timestamps in the export and for date functions in the query. A timezone set
                    in the query, such as with <code>toTimeZone(timestamp, 'UTC')</code>, takes precedence.
                </>
            }
            help={help}
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
