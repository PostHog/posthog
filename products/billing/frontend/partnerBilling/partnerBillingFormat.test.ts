import { formatAppliedLimits } from './partnerBillingFormat'

describe('formatAppliedLimits', () => {
    it("shows an organization's own limit, the default where it has none, and no limit where its own is null", () => {
        const limits = formatAppliedLimits(
            { session_replay: 100, surveys: null },
            { product_analytics: 500, session_replay: 250, surveys: 50 },
            { product_analytics: 'Product analytics', session_replay: 'Session replay', surveys: 'Surveys' }
        )

        expect(limits.map(({ label }) => label)).toEqual([
            'Product analytics: Default $500',
            'Session replay: $100',
            'Surveys: No limit',
        ])
    })
})
