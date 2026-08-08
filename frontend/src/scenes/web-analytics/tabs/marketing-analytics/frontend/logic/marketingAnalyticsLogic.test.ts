import { IntervalType } from '~/types'

import { buildMarketingAnalyticsSearchParams, MarketingAnalyticsTab } from './marketingAnalyticsLogic'

describe('buildMarketingAnalyticsSearchParams', () => {
    // The column layout params are owned by marketingAnalyticsTableLogic, seeded into the URL.
    const columnParams =
        'select=campaign_name%2Ctotal_cost&pinned_columns=campaign_name&order_column=total_cost&order_direction=DESC'

    const values = {
        activeTab: MarketingAnalyticsTab.ATTRIBUTION,
        dateFilter: { dateFrom: '-30d', dateTo: null, interval: 'day' as IntervalType },
    }

    it('keeps the table column params when writing its own params', () => {
        const params = new URLSearchParams(buildMarketingAnalyticsSearchParams(columnParams, values))

        // The column layout survives alongside the params this logic writes.
        expect(params.get('select')).toBe('campaign_name,total_cost')
        expect(params.get('pinned_columns')).toBe('campaign_name')
        expect(params.get('order_column')).toBe('total_cost')
        expect(params.get('order_direction')).toBe('DESC')
        expect(params.get('tab')).toBe(MarketingAnalyticsTab.ATTRIBUTION)
        expect(params.get('date_from')).toBe('-30d')
    })

    it('deletes a stale param when its value returns to the default', () => {
        // `tab` is present in the seed but the tab is now the default DASHBOARD.
        const params = new URLSearchParams(
            buildMarketingAnalyticsSearchParams(`${columnParams}&tab=attribution`, {
                ...values,
                activeTab: MarketingAnalyticsTab.DASHBOARD,
            })
        )

        expect(params.has('tab')).toBe(false)
        // A foreign param is still preserved.
        expect(params.get('select')).toBe('campaign_name,total_cost')
    })
})
