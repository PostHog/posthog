import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import type { CampaignAuditResult, UtmAuditResponse, UtmEvent } from './utmAuditLogic'
import { utmAuditLogic } from './utmAuditLogic'

function campaign(overrides: Partial<CampaignAuditResult> & { campaign_name: string }): CampaignAuditResult {
    return {
        campaign_id: '1',
        source_name: 'google',
        spend: 100,
        clicks: 10,
        impressions: 100,
        has_utm_events: false,
        event_count: 0,
        issues: [],
        ...overrides,
    }
}

function utmEvent(utm_campaign: string): UtmEvent {
    return {
        utm_campaign,
        utm_source: 'google',
        event_count: 10,
        campaign_match: 'none',
        source_match: 'auto',
        matched_campaign: null,
    }
}

function auditResponse(results: CampaignAuditResult[], events: UtmEvent[]): UtmAuditResponse {
    return {
        total_campaigns: results.length,
        campaigns_with_issues: results.filter((r) => r.issues.length > 0).length,
        campaigns_without_issues: results.filter((r) => r.issues.length === 0).length,
        total_spend_at_risk: 0,
        results,
        all_utm_events: events,
    }
}

const NOT_LINKED = {
    field: 'utm_campaign',
    severity: 'error' as const,
    kind: 'not_linked' as const,
    message: 'No pageview events found',
    alternative_sources: [],
    shared_with_integrations: [],
    suggested_actions: ['fix_platform_urls' as const],
}

describe('utmAuditLogic', () => {
    let logic: ReturnType<typeof utmAuditLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/marketing_analytics/utm_audit': () => [200, auditResponse([], [])],
            },
        })
        initKeaTests()
        marketingAnalyticsSettingsLogic.mount()
        logic = utmAuditLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('pendingMappings', () => {
        it('maps every selected utm_campaign onto a single selected campaign', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse(
                    [campaign({ campaign_name: 'Summer Sale' })],
                    [utmEvent('summer-sale-a'), utmEvent('summer-sale-b')]
                )
            )
            logic.actions.setSelectedCampaigns(['Summer Sale'])
            logic.actions.setSelectedUtmCampaigns(['summer-sale-a', 'summer-sale-b'])

            await expectLogic(logic).toMatchValues({
                pendingMappings: [
                    expect.objectContaining({ matchValue: 'Summer Sale', utmCampaign: 'summer-sale-a' }),
                    expect.objectContaining({ matchValue: 'Summer Sale', utmCampaign: 'summer-sale-b' }),
                ],
            })
        })

        it('routes each utm_campaign to its closest campaign and drops the far-off ones', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse(
                    [
                        campaign({ campaign_name: 'Summer Sale', campaign_id: '1' }),
                        campaign({ campaign_name: 'Winter Sale', campaign_id: '2' }),
                    ],
                    [utmEvent('summer sale'), utmEvent('winter sale'), utmEvent('totally-unrelated')]
                )
            )
            logic.actions.setSelectedCampaigns(['Summer Sale', 'Winter Sale'])
            logic.actions.setSelectedUtmCampaigns(['summer sale', 'winter sale', 'totally-unrelated'])

            await expectLogic(logic).toMatchValues({
                pendingMappings: [
                    expect.objectContaining({ campaignName: 'Summer Sale', utmCampaign: 'summer sale' }),
                    expect.objectContaining({ campaignName: 'Winter Sale', utmCampaign: 'winter sale' }),
                ],
            })
        })
    })

    describe('autoMappingSuggestions', () => {
        it('proposes utm_campaign values that differ only by capitalization', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse([campaign({ campaign_name: 'Summer Sale' })], [utmEvent('summer sale')])
            )

            await expectLogic(logic).toMatchValues({
                autoMappingSuggestions: [
                    expect.objectContaining({
                        integration: 'GoogleAds',
                        matchValue: 'Summer Sale',
                        utmCampaign: 'summer sale',
                        reason: 'case_only',
                    }),
                ],
            })
        })

        it('leaves an exact match alone', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse([campaign({ campaign_name: 'summer sale' })], [utmEvent('summer sale')])
            )

            await expectLogic(logic).toMatchValues({ autoMappingSuggestions: [] })
        })

        it('proposes a near miss only for a campaign the audit flagged', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse(
                    [
                        campaign({ campaign_name: 'Spring Sale', campaign_id: '1', issues: [NOT_LINKED] }),
                        campaign({ campaign_name: 'Autumn Sale', campaign_id: '2' }),
                    ],
                    [utmEvent('spring_sale'), utmEvent('autumn_sale')]
                )
            )

            await expectLogic(logic).toMatchValues({
                autoMappingSuggestions: [
                    expect.objectContaining({ campaignName: 'Spring Sale', utmCampaign: 'spring_sale' }),
                ],
            })
        })

        it('skips utm_campaign values that are already mapped somewhere', async () => {
            marketingAnalyticsSettingsLogic.actions.updateCampaignNameMappings({
                MetaAds: { 'Some Other Campaign': ['summer sale'] },
            })
            logic.actions.loadAuditDataSuccess(
                auditResponse([campaign({ campaign_name: 'Summer Sale' })], [utmEvent('summer sale')])
            )

            await expectLogic(logic).toMatchValues({ autoMappingSuggestions: [] })
        })
    })

    describe('applyMappings', () => {
        it('writes every pair into campaign_name_mappings in one update', async () => {
            logic.actions.loadAuditDataSuccess(
                auditResponse(
                    [campaign({ campaign_name: 'Summer Sale' })],
                    [utmEvent('summer-sale-a'), utmEvent('summer-sale-b')]
                )
            )
            logic.actions.setSelectedCampaigns(['Summer Sale'])
            logic.actions.setSelectedUtmCampaigns(['summer-sale-a', 'summer-sale-b'])

            logic.actions.applyMappings(logic.values.pendingMappings)

            await expectLogic(marketingAnalyticsSettingsLogic).toMatchValues({
                marketingAnalyticsConfig: expect.objectContaining({
                    campaign_name_mappings: { GoogleAds: { 'Summer Sale': ['summer-sale-a', 'summer-sale-b'] } },
                }),
            })
            await expectLogic(logic).toMatchValues({ selectedCampaigns: [], selectedUtmCampaigns: [] })
        })
    })
})
