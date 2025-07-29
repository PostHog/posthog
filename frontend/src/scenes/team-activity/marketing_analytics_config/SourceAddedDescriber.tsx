import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import {
    ExternalTable,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

export const SourceAddedDescriber = ({
    sourceKey,
    columnKey,
    mappedField,
}: {
    sourceKey: string
    columnKey: string
    mappedField: string
}): JSX.Element => {
    const { externalTables } = useValues(marketingAnalyticsLogic)

    const table = externalTables.find((t: ExternalTable) => t.source_map_id === sourceKey)

    return (
        <>
            started configuring <b>{table?.schema_name || 'Unknown source'}</b>{' '}
            <Link to={urls.settings('project', 'marketing-settings')} target="_blank">
                marketing source
            </Link>{' '}
            by mapping <code>{columnKey}</code> column to <code>{mappedField}</code>
        </>
    )
}
