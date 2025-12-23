import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { FilterBar } from 'lib/components/FilterBar'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

const DATE_FILTER_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 90 days',
        values: ['-90d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(90, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 180 days',
        values: ['-180d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(180, 'days'), date),
        defaultInterval: 'week',
    },
    {
        key: 'This month',
        values: ['mStart', 'mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('m'), date.endOf('m')),
        defaultInterval: 'day',
    },
    {
        key: 'Last month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date),
        defaultInterval: 'week',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

export function CustomerAnalyticsFilters(): JSX.Element {
    const {
        businessType,
        dateFilter: { dateTo, dateFrom },
        groupsEnabled,
        groupOptions,
        selectedGroupType,
    } = useValues(customerAnalyticsSceneLogic)

    const { setBusinessType, setDates, setSelectedGroupType } = useActions(customerAnalyticsSceneLogic)
    const { reportCustomerAnalyticsDashboardBusinessModeChanged, reportCustomerAnalyticsDashboardDateFilterApplied } =
        useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)
    // TODO: Add CTA for cross sell
    const b2bDisabledReason = groupsEnabled ? '' : 'Group analytics add-on is not enabled'

    return (
        <FilterBar
            left={
                <div className="flex flex-row items-center gap-2">
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(dateFrom, dateTo) => {
                            setDates(dateFrom, dateTo)
                            reportCustomerAnalyticsDashboardDateFilterApplied({ filter: { dateFrom, dateTo } })
                            addProductIntent({
                                product_type: ProductKey.CUSTOMER_ANALYTICS,
                                intent_context: ProductIntentContext.CUSTOMER_ANALYTICS_DASHBOARD_FILTERS_CHANGED,
                            })
                        }}
                        dateOptions={DATE_FILTER_DATE_OPTIONS}
                        size="small"
                    />
                    <LemonSegmentedButton
                        size="small"
                        options={[
                            { label: 'B2C', value: 'b2c', 'data-attr': 'customer-analytics-b2c' },
                            {
                                label: 'B2B',
                                value: 'b2b',
                                'data-attr': 'customer-analytics-b2b',
                                disabledReason: b2bDisabledReason,
                            },
                        ]}
                        value={businessType}
                        onChange={(value) => {
                            setBusinessType(value)
                            reportCustomerAnalyticsDashboardBusinessModeChanged({ business_mode: value })
                            addProductIntent({
                                product_type: ProductKey.CUSTOMER_ANALYTICS,
                                intent_context: ProductIntentContext.CUSTOMER_ANALYTICS_DASHBOARD_BUSINESS_MODE_CHANGED,
                            })
                        }}
                    />
                    {businessType === 'b2b' && (
                        <LemonSelect
                            size="small"
                            data-attr="customer-analytics-group-type"
                            options={groupOptions}
                            value={selectedGroupType}
                            onChange={setSelectedGroupType}
                        />
                    )}
                </div>
            }
            right={
                <AppShortcut
                    name="CustomerAnalyticsRefresh"
                    keybind={[keyBinds.refresh]}
                    intent="Refresh data"
                    interaction="click"
                    scope={Scene.CustomerAnalytics}
                >
                    <Tooltip title="Refresh data">
                        <ReloadAll />
                    </Tooltip>
                </AppShortcut>
            }
        />
    )
}
