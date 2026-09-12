import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import {
    marketingAnalyticsLogic,
    MarketingAnalyticsTab,
    SetupSection,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NewMarketingAnalyticsDashboard } from './NewMarketingAnalyticsDashboard'

jest.mock('~/queries/Query/Query', () => ({ Query: () => null }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable', () => ({
    AttributionTable: () => null,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab', () => ({
    AttributionTab: () => null,
}))

it('reuses source suggestions, remembers collapse and opens their review in Setup', async () => {
    useMocks({
        get: {
            '/api/projects/:team_id/marketing_analytics/setup_plan': () => [
                200,
                {
                    suggestions: [
                        {
                            id: 'connect_source:GoogleAds',
                            kind: 'connect_source',
                            also_recommended: [],
                            title: 'Connect Google Ads',
                            evidence: 'Traffic contains Google Ads tags.',
                            integration: 'GoogleAds',
                            source: 'deterministic',
                            severity: 'info',
                            unlocks: [],
                            apply: { op: 'open_source_wizard', kind: 'GoogleAds' },
                        },
                    ],
                    readiness: [],
                    degraded: [],
                    truncated: false,
                    summary: '',
                },
            ],
        },
    })
    initKeaTests()
    localStorage.removeItem('marketing-source-suggestions-expanded')
    const unmountMarketing = marketingAnalyticsLogic.mount()
    const unmountSetup = setupPlanLogic.mount()
    const view = render(<NewMarketingAnalyticsDashboard />)
    try {
        await screen.findByText('Connect Google Ads')
        fireEvent.click(screen.getByText('Suggested ad sources (1)'))
        expect(localStorage.getItem('marketing-source-suggestions-expanded')).toBe('false')
        view.unmount()
        render(<NewMarketingAnalyticsDashboard />)
        expect(
            screen.getByText('Suggested ad sources (1)').closest('[aria-expanded]')?.getAttribute('aria-expanded')
        ).toBe('false')
        fireEvent.click(screen.getByText('Suggested ad sources (1)'))
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
        await waitFor(() => expect(marketingAnalyticsLogic.values.activeTab).toBe(MarketingAnalyticsTab.SETUP))
        expect(marketingAnalyticsLogic.values.setupSection).toBe(SetupSection.SOURCES)
        expect(setupPlanLogic.values.reviewingSuggestion?.id).toBe('connect_source:GoogleAds')
        fireEvent.click(screen.getByText('Dismiss'))
        await waitFor(() => expect(screen.queryByText('Suggested ad sources (1)')).toBeNull())
    } finally {
        cleanup()
        unmountSetup()
        unmountMarketing()
    }
})
