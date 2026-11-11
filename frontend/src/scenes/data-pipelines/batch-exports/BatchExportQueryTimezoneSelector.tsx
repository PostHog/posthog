import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { QueryTimezoneChoice, batchExportHogQLQueryLogic } from './batchExportHogQLQueryLogic'

export function BatchExportQueryTimezoneSelector(): JSX.Element {
    const formLogic = useMountedLogic(batchExportConfigFormLogic)
    const { configurationErrors } = useValues(formLogic)
    const logic = batchExportHogQLQueryLogic(formLogic.props)
    const { projectTimezone, followsProjectModifier, queryTimezoneChoice } = useValues(logic)
    const { setQueryTimezone } = useActions(logic)

    let help: React.ReactNode = null
    if (followsProjectModifier) {
        help = (
            <>
                This export follows the project's <code>convertToProjectTimezone</code> modifier, which is set through
                the API. Choose an option to set the timezone for this export only.
            </>
        )
    } else if (queryTimezoneChoice === 'project_timezone') {
        help = (
            <>
                If the project timezone changes in{' '}
                <Link to={urls.settings('environment-customization', 'date-and-time')} target="_blank">
                    project settings
                </Link>
                , this export uses the new timezone from its next run.
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
            <LemonSelect<QueryTimezoneChoice>
                fullWidth
                value={queryTimezoneChoice}
                onSelect={setQueryTimezone}
                options={[
                    { value: 'utc', label: 'UTC' },
                    { value: 'project_timezone', label: `Project timezone (${projectTimezone})` },
                ]}
                data-attr="batch-export-hogql-query-timezone"
            />
        </LemonField.Pure>
    )
}
