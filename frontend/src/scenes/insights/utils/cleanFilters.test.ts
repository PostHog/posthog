import { cleanFilters } from './cleanFilters'
import { ChartDisplayType } from '~/types'
import { ShownAsValue } from 'lib/constants'

describe('cleanFilters', () => {
    it('switches display to table if moving from TRENDS to RETENTION', () => {
        expect(
            cleanFilters(
                { insight: 'RETENTION', display: ChartDisplayType.ActionsLineGraphLinear },
                { insight: 'TRENDS', display: ChartDisplayType.ActionsLineGraphLinear }
            )
        ).toEqual(expect.objectContaining({ insight: 'RETENTION', display: ChartDisplayType.ActionsTable }))
    })

    it('removes shownas if moving from stickiness to trends', () => {
        expect(
            cleanFilters(
                { insight: 'TRENDS', shown_as: ShownAsValue.STICKINESS },
                { insight: 'STICKINESS', shown_as: ShownAsValue.STICKINESS }
            )
        ).toEqual(expect.objectContaining({ insight: 'TRENDS', shown_as: undefined }))
    })
})
