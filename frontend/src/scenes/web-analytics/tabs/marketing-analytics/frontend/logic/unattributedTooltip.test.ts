import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { unattributedTooltip } from './marketingAttributionLogic'

describe('unattributedTooltip', () => {
    it('names the sentinel row for channel', () => {
        expect(unattributedTooltip(MarketingAnalyticsAttributionBreakdown.Channel)).toBe(
            'Sessions with no channel — the ones shown as "Unknown" — stop counting as touchpoints, and their credit is shared across the remaining ones.'
        )
    })

    it('names the sentinel row for referring domain', () => {
        expect(unattributedTooltip(MarketingAnalyticsAttributionBreakdown.ReferringDomain)).toContain(
            'the ones shown as "$direct"'
        )
    })

    it('names the "(none)" row for the plain UTM breakdowns', () => {
        expect(unattributedTooltip(MarketingAnalyticsAttributionBreakdown.Campaign)).toContain(
            'the ones shown as "(none)"'
        )
    })

    it("names no row for source, whose label depends on the team's source normalization", () => {
        // An empty utm_source is displayed via the organic bucket, but that substitution happens before
        // source normalization runs — a team listing "organic" among an ad platform's custom UTM sources
        // sees those touchpoints under the platform's name instead. Naming any row here would be a guess.
        const tooltip = unattributedTooltip(MarketingAnalyticsAttributionBreakdown.Source)
        expect(tooltip).toBe(
            'Sessions with no source stop counting as touchpoints, and their credit is shared across the remaining ones.'
        )
        expect(tooltip).not.toContain('shown as')
    })
})
