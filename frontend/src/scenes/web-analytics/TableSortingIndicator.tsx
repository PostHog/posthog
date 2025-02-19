import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconSort } from 'lib/lemon-ui/icons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebAnalyticsOrderByFields } from '~/queries/schema/schema-general'

const SORT_BY_TO_LABEL: Record<WebAnalyticsOrderByFields, string> = {
    [WebAnalyticsOrderByFields.Visitors]: 'Visitors',
    [WebAnalyticsOrderByFields.Views]: 'Views',
    [WebAnalyticsOrderByFields.Clicks]: 'Clicks',
    [WebAnalyticsOrderByFields.BounceRate]: 'Bounce rate',
    [WebAnalyticsOrderByFields.AverageScrollPercentage]: 'Average scroll percentage',
    [WebAnalyticsOrderByFields.ScrollGt80Percentage]: 'Scroll > 80%',
    [WebAnalyticsOrderByFields.TotalConversions]: 'Total conversions',
    [WebAnalyticsOrderByFields.UniqueConversions]: 'Unique conversions',
    [WebAnalyticsOrderByFields.ConversionRate]: 'Conversion rate',
    [WebAnalyticsOrderByFields.ConvertingUsers]: 'Converting users',
}

export const TableSortingIndicator = (): JSX.Element | null => {
    const { tablesOrderBy } = useValues(webAnalyticsLogic)
    const { clearTablesOrderBy } = useActions(webAnalyticsLogic)

    if (!tablesOrderBy) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSort className={clsx({ 'rotate-180': tablesOrderBy[1] === 'ASC' })} />}
            sideIcon={<IconX />}
            onClick={clearTablesOrderBy}
        >
            <span>Sort by: {SORT_BY_TO_LABEL[tablesOrderBy[0]]}</span>
        </LemonButton>
    )
}
