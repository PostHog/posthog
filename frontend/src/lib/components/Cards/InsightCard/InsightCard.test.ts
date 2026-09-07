import { DashboardPlacement } from '~/types'

import { shouldRenderInsightCardViz } from './InsightCard'

describe('InsightCard', () => {
    it.each([
        {
            name: 'renders a tile that is on screen',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, inView: true },
            expected: true,
        },
        {
            name: 'unmounts a tile that is off screen',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, inView: false },
            expected: false,
        },
        {
            name: 'renders exports regardless of visibility',
            input: { isStorybook: false, placement: DashboardPlacement.Export, inView: false },
            expected: true,
        },
    ])('$name', ({ input, expected }) => {
        expect(shouldRenderInsightCardViz(input)).toBe(expected)
    })
})
