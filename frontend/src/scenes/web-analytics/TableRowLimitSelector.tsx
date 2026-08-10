import { useActions, useValues } from 'kea'

import { IconList } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { WEB_ANALYTICS_TABLE_ROW_LIMIT_OPTIONS, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ProductTab } from './common'

export const TableRowLimitSelector = (): JSX.Element | null => {
    const { tablesRowLimit, productTab } = useValues(webAnalyticsLogic)
    const { setTablesRowLimit } = useActions(webAnalyticsLogic)

    if (productTab !== ProductTab.ANALYTICS) {
        return null
    }

    return (
        <LemonSelect
            size="small"
            icon={<IconList />}
            value={tablesRowLimit}
            onChange={setTablesRowLimit}
            options={WEB_ANALYTICS_TABLE_ROW_LIMIT_OPTIONS.map((limit) => ({
                value: limit,
                label: `${limit} rows`,
            }))}
            tooltip="Rows to show in each table"
        />
    )
}
