import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MarketingAnalyticsScene } from 'scenes/marketing-analytics/MarketingAnalyticsScene'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import {
    marketingAnalyticsLogic,
    MarketingAnalyticsTab,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DetectedSources } from 'products/marketing_analytics/frontend/dashboard/DetectedSources'
import { NewMarketingAnalyticsDashboard } from 'products/marketing_analytics/frontend/dashboard/NewMarketingAnalyticsDashboard'

jest.mock('products/data_warehouse/frontend/shared/components/SourceIcon', () => ({ SourceIcon: () => null }))

jest.mock('~/queries/Query/Query', () => ({ Query: () => null }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable', () => ({
    AttributionTable: () => null,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab', () => ({
    AttributionTab: () => null,
}))

it.each([false, true])('keeps suggestions actionable with synced data %s', async (hasSyncedData) => {
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
    const unmountFeatureFlags = featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true })
    const unmountOnboarding = marketingOnboardingLogic.mount()
    marketingOnboardingLogic.actions.completeOnboarding()
    localStorage.removeItem('marketing-source-suggestions-expanded')
    const unmountMarketing = marketingAnalyticsLogic.mount()
    const readiness = jest
        .spyOn(marketingAnalyticsLogic.selectors, 'hasSyncedMarketingSources')
        .mockReturnValue(hasSyncedData)
    const unmountSetup = setupPlanLogic.mount()
    const view = render(<NewMarketingAnalyticsDashboard />)
    try {
        await screen.findByText('Connect your ad platforms')
        expect(screen.queryByText('Your connections are getting ready')).toBeNull()
        expect(screen.queryByText('You can leave this page. Your import will continue in the background.')).toBeNull()
        expect(screen.queryByText('Your marketing data in one place') !== null).toBe(!hasSyncedData)
        expect(screen.getByText('Google Ads')).not.toBeNull()
        view.unmount()
        render(<NewMarketingAnalyticsDashboard />)
        expect(screen.getByText('Google Ads')).not.toBeNull()
        fireEvent.click(screen.getByText('Browse integrations'))
        await screen.findByText('Connect your marketing sources')
        expect(screen.queryByText('Google Search Console')).toBeNull()
        expect(marketingAnalyticsLogic.values.activeTab).toBe(MarketingAnalyticsTab.DASHBOARD)
        fireEvent.click(screen.getByText('Back to suggestions'))
        expect(screen.getByText('Google Ads')).not.toBeNull()
        expect(screen.queryByText('Review in setup')).toBeNull()
        fireEvent.click(screen.getByText('Dismiss'))
        await waitFor(() => expect(screen.queryByText('Google Ads')).toBeNull())
    } finally {
        cleanup()
        readiness.mockRestore()
        unmountFeatureFlags()
        setupPlanLogic.actions.restoreAllDismissed()
        localStorage.removeItem('marketing-source-suggestions-expanded')
        unmountOnboarding()
        localStorage.removeItem('marketing-analytics-onboarding-completed')
        unmountSetup()
        unmountMarketing()
    }
})

it.each([
    [false, false, 'Finding your ad platforms'],
    [true, false, 'Finding your ad platforms'],
    [false, true, 'Could not check your events'],
])('distinguishes scan loading %s and failure %s', (loading, failed, heading) => {
    initKeaTests()
    const unmountFlags = featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true })
    const unmountSetup = setupPlanLogic.mount()
    const plan = jest.spyOn(setupPlanLogic.selectors, 'setupPlan').mockReturnValue(null)
    const planLoading = jest.spyOn(setupPlanLogic.selectors, 'setupPlanLoading').mockReturnValue(loading)
    const planFailed = jest.spyOn(setupPlanLogic.selectors, 'setupPlanFailed').mockReturnValue(failed)
    try {
        render(<DetectedSources />)
        expect(screen.getByText(heading)).not.toBeNull()
    } finally {
        cleanup()
        plan.mockRestore()
        planLoading.mockRestore()
        planFailed.mockRestore()
        unmountSetup()
        unmountFlags()
    }
})

it('opens the feedback form from the source onboarding header', async () => {
    initKeaTests()
    const unmountFlags = featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true })
    try {
        render(<MarketingAnalyticsScene />)
        fireEvent.click(screen.getByText('Send feedback'))
        await waitFor(() => {
            expect(supportLogic.values.sendSupportRequest.kind).toBe('feedback')
            expect(supportLogic.values.isEmailFormOpen).toBe(true)
        })
    } finally {
        cleanup()
        unmountFlags()
    }
})
