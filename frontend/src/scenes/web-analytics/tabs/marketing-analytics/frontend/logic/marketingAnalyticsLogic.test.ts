import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { marketingAnalyticsLogic, MarketingAnalyticsTab } from './marketingAnalyticsLogic'

describe('marketingAnalyticsLogic', () => {
    let logic: ReturnType<typeof marketingAnalyticsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team/warehouse_saved_queries/': { results: [] },
                '/api/environments/:team/external_data_sources/': { results: [] },
                '/api/projects/:team/external_data_sources/': { results: [] },
                '/api/environments/:team/warehouse_tables/': { results: [] },
                '/api/projects/:team/warehouse_tables/': { results: [] },
                '/api/environments/:team/integrations/': { results: [] },
                '/api/projects/:team/integrations/': { results: [] },
            },
        })
        initKeaTests()
        // buildUrl reads window.location.search directly, so seed the real jsdom URL
        // with the column params owned by marketingAnalyticsTableLogic.
        window.history.replaceState(
            {},
            '',
            '/web/marketing?select=campaign_name%2Ctotal_cost&pinned_columns=campaign_name&order_column=total_cost&order_direction=DESC'
        )
        logic = marketingAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps the table column params in the URL when a filter changes', () => {
        // Changing a filter (here the tab) must not wipe the column layout the table logic wrote.
        logic.actions.setActiveTab(MarketingAnalyticsTab.ATTRIBUTION)

        expect(router.values.searchParams).toMatchObject({
            select: 'campaign_name,total_cost',
            pinned_columns: 'campaign_name',
            order_column: 'total_cost',
            order_direction: 'DESC',
            tab: MarketingAnalyticsTab.ATTRIBUTION,
        })
    })
})
