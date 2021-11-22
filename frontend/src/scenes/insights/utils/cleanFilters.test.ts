import { cleanFilters } from './cleanFilters'
import { ChartDisplayType, InsightType } from '~/types'
import { ShownAsValue } from 'lib/constants'

describe('cleanFilters', () => {
    it('switches display to table if moving from TRENDS to RETENTION', () => {
        expect(
            cleanFilters(
                { insight: InsightType.RETENTION, display: ChartDisplayType.ActionsLineGraphLinear },
                { insight: InsightType.TRENDS, display: ChartDisplayType.ActionsLineGraphLinear }
            )
        ).toEqual(expect.objectContaining({ insight: InsightType.RETENTION, display: ChartDisplayType.ActionsTable }))
    })

    it('removes shownas if moving from stickiness to trends', () => {
        expect(
            cleanFilters(
                { insight: InsightType.TRENDS, shown_as: ShownAsValue.STICKINESS },
                { insight: InsightType.STICKINESS, shown_as: ShownAsValue.STICKINESS }
            )
        ).toEqual(expect.objectContaining({ insight: InsightType.TRENDS, shown_as: undefined }))
    })

    it('removes breakdown when adding breakdowns', () => {
        const cleanedFilters = cleanFilters(
            {
                breakdowns: [{ property: '$browser', type: 'event' }],
                insight: InsightType.FUNNELS,
                funnel_viz_type: 'steps',
            },
            { breakdown: '$browser', insight: InsightType.FUNNELS, funnel_viz_type: 'steps' }
        )

        console.log(cleanedFilters)

        expect(cleanedFilters).not.toHaveProperty('breakdown')

        expect(cleanedFilters).toEqual(
            expect.objectContaining({ breakdowns: [{ property: '$browser', type: 'event' }] })
        )
    })
})
