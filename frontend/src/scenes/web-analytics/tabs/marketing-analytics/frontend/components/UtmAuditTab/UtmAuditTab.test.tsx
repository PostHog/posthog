import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { utmAuditLogic } from '../../logic/utmAuditLogic'
import { UtmAuditTab } from './UtmAuditTab'

const SOURCE_MISMATCH_AUDIT = {
    total_campaigns: 1,
    campaigns_with_issues: 1,
    campaigns_without_issues: 0,
    total_spend_at_risk: 200,
    results: [
        {
            campaign_name: 'Brand Campaign',
            campaign_id: '789',
            source_name: 'google',
            spend: 200,
            clicks: 80,
            impressions: 2000,
            has_utm_events: false,
            event_count: 0,
            issues: [
                {
                    field: 'utm_source',
                    severity: 'warning',
                    kind: 'unknown_source',
                    message: "No events tagged with utm_source='google'",
                    alternative_sources: [{ utm_source: 'newsletter', event_count: 30 }],
                    shared_with_integrations: [],
                    suggested_actions: ['fix_platform_urls', 'add_source_mapping'],
                },
            ],
        },
    ],
    all_utm_events: [
        {
            utm_campaign: 'brand-q1',
            utm_source: 'newsletter',
            event_count: 20,
            campaign_match: 'none',
            source_match: 'none',
            matched_campaign: null,
        },
        {
            utm_campaign: 'brand-q2',
            utm_source: 'newsletter',
            event_count: 10,
            campaign_match: 'none',
            source_match: 'none',
            matched_campaign: null,
        },
    ],
}

describe('UtmAuditTab', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/marketing_analytics/utm_audit': () => [200, SOURCE_MISMATCH_AUDIT],
            },
        })
        initKeaTests()
        utmAuditLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('expands a source mismatch into the alternative source and the fixes for it', async () => {
        render(<UtmAuditTab />)

        const tag = await screen.findByText('Source mismatch')
        // Previously the whole explanation was a one-line tooltip, so nothing below existed.
        expect(screen.queryByText('utm_source=newsletter')).toBeNull()

        fireEvent.click(tag)

        await waitFor(() => expect(screen.getByText('utm_source=newsletter')).toBeTruthy())
        expect(screen.getByText('30 pageviews')).toBeTruthy()
        expect(screen.getByText(/Count "newsletter" as Google Ads/)).toBeTruthy()
        expect(screen.getByText('utm_source=google')).toBeTruthy()
    })

    it('maps several utm_campaign values to one campaign in a single action', async () => {
        render(<UtmAuditTab />)

        fireEvent.click(await screen.findByLabelText('Select Brand Campaign'))
        fireEvent.click(screen.getByLabelText('Select brand-q1'))
        fireEvent.click(screen.getByLabelText('Select brand-q2'))

        // The bar used to hold one campaign per side, so it could only ever offer "Map campaign".
        await waitFor(() => expect(screen.getByText('Map 2 campaigns')).toBeTruthy())
    })
})
