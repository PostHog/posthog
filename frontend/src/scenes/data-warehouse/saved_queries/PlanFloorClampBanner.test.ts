import { planFloorClampMessage } from './PlanFloorClampBanner'

describe('planFloorClampMessage', () => {
    it.each([
        [
            'view' as const,
            900,
            3600,
            "Your plan's refresh limit set this view to refresh every hour. It refreshed every 15 minutes before.",
        ],
        [
            'endpoint' as const,
            1800,
            86400,
            "Your plan's refresh limit set this endpoint to refresh every day. It refreshed every 30 minutes before.",
        ],
        ['view' as const, null, 21600, "Your plan's refresh limit set this view to refresh every 6 hours."],
    ])('describes a %s rewrite from %s to %s seconds', (subject, previousSeconds, planFloorSeconds, expected) => {
        expect(planFloorClampMessage(subject, previousSeconds, planFloorSeconds)).toEqual(expected)
    })
})
