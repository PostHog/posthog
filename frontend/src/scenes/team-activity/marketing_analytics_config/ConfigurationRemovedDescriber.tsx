import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import {
    ExternalTable,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

export const ConfigurationRemovedDescriber = ({
    sourceKey,
    columnKey,
}: {
    sourceKey: string
    columnKey: string
}): JSX.Element => {
    const { externalTables } = useValues(marketingAnalyticsLogic)

    const table = externalTables.find((t: ExternalTable) => t.source_map_id === sourceKey)

    return (
        <>
            cleared{' '}
            <Link to={urls.settings('project', 'marketing-settings')} target="_blank">
                marketing source
            </Link>{' '}
            configuration by removing <code>{columnKey}</code> column mapping for <b>{table?.schema_name}</b>
        </>
    )
}
