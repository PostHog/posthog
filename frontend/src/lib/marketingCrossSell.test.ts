import posthog from 'posthog-js'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import {
    captureMarketingCrossSellClick,
    captureMarketingCrossSellSourceCreated,
    getMarketingCrossSellAttribution,
} from './marketingCrossSell'

describe('Marketing cross-sell attribution', () => {
    beforeEach(() => {
        sessionStorage.clear()
        jest.spyOn(posthog, 'get_distinct_id').mockReturnValue('test-user')
        jest.spyOn(posthog, 'capture').mockClear()
        jest.spyOn(Date, 'now').mockReturnValue(100000000)
    })
    afterEach(() => {
        jest.restoreAllMocks()
        sessionStorage.clear()
    })

    it('links the first source to the latest click and consumes the attribution', () => {
        captureMarketingCrossSellClick(42, WebStatsBreakdown.InitialChannelType, false)
        const first = getMarketingCrossSellAttribution(42)!
        captureMarketingCrossSellClick(42, WebStatsBreakdown.InitialUTMCampaign, true)
        const latest = getMarketingCrossSellAttribution(42)!
        expect(latest.cross_sell_id).not.toBe(first.cross_sell_id)
        captureMarketingCrossSellSourceCreated(first, 'outdated-source', 'GoogleAds')
        expect(getMarketingCrossSellAttribution(42)).toEqual(latest)
        captureMarketingCrossSellSourceCreated(latest, 'source-42', 'GoogleAds')
        captureMarketingCrossSellSourceCreated(latest, 'another-source', 'MetaAds')
        const conversions = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([name]) => name === 'web analytics marketing cross sell source created')
        expect(conversions).toEqual([
            [
                'web analytics marketing cross sell source created',
                expect.objectContaining({
                    cross_sell_id: latest.cross_sell_id,
                    team_id: 42,
                    has_connected_sources: true,
                    source_id: 'source-42',
                    source_type: 'GoogleAds',
                }),
            ],
        ])
        expect(getMarketingCrossSellAttribution(42)).toBeNull()
    })

    it.each(['another project', 'another user', 'expired', 'future'])('rejects %s attribution', (reason) => {
        captureMarketingCrossSellClick(42, WebStatsBreakdown.InitialUTMSource, false)
        if (reason === 'another user') {
            jest.mocked(posthog.get_distinct_id).mockReturnValue('other-user')
        } else if (reason === 'expired') {
            jest.mocked(Date.now).mockReturnValue(100000000 + 24 * 60 * 60 * 1000 + 1)
        } else if (reason === 'future') {
            jest.mocked(Date.now).mockReturnValue(99999999)
        }
        expect(getMarketingCrossSellAttribution(reason === 'another project' ? 43 : 42)).toBeNull()
    })

    it('still captures a click when browser storage is unavailable', () => {
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('Storage disabled')
        })
        expect(() => captureMarketingCrossSellClick(42, WebStatsBreakdown.InitialChannelType, false)).not.toThrow()
        expect(posthog.capture).toHaveBeenCalledWith(
            'web analytics marketing cross sell clicked',
            expect.objectContaining({ team_id: 42 })
        )
    })
})
