import { planFloorClampMessage } from './PlanFloorClampBanner'

describe('planFloorClampMessage', () => {
    it.each([
        [
            'view' as const,
            900,
            3600,
            'This view now refreshes every hour, the fastest your plan allows. It refreshed every 15 minutes before.',
        ],
        [
            'endpoint' as const,
            1800,
            86400,
            'This endpoint now refreshes every day, the fastest your plan allows. It refreshed every 30 minutes before.',
        ],
        ['view' as const, null, 21600, 'This view now refreshes every 6 hours, the fastest your plan allows.'],
    ])('describes a %s rewrite from %s to %s seconds', (subject, previousSeconds, planFloorSeconds, expected) => {
        expect(planFloorClampMessage(subject, previousSeconds, planFloorSeconds)).toEqual(expected)
    })
})
