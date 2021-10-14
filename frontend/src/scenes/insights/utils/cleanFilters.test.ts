import { cleanFilters } from './cleanFilters'
import { ChartDisplayType } from '~/types'

describe('cleanFilters', () => {
    it('switches display to table if moving from TRENDS to RETENTION', () => {
        expect(
            cleanFilters(
                { insight: 'RETENTION', display: ChartDisplayType.ActionsLineGraphLinear },
                { insight: 'TRENDS', display: ChartDisplayType.ActionsLineGraphLinear }
            )
        ).toEqual(expect.objectContaining({ insight: 'RETENTION', display: ChartDisplayType.ActionsTable }))
    })
})
