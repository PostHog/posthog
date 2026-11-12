import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { ProductUsageLegend } from './ProductUsageLegend'

const props = {
    series: BOOK_ACTIVITY_MATRIX_MOCK.series,
    groupings: BOOK_ACTIVITY_MATRIX_MOCK.groupings,
    grouping: 'role',
    onGroupingChange: jest.fn(),
    selectedSeries: [],
    onSelectedSeriesChange: jest.fn(),
}

describe('ProductUsageLegend', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('explains first-use marks only when enabled, and gives Users its own key', () => {
        const { rerender } = render(<ProductUsageLegend {...props} />)
        expect(screen.queryByText('First use ever')).toBeNull()
        rerender(<ProductUsageLegend {...props} includeFirstUse />)
        expect(screen.getByText('First use ever')).toBeTruthy()
        rerender(<ProductUsageLegend {...props} mode="users" includeFirstUse />)
        expect(screen.getByText('Names = most active first · +N more = show all · New = first use ever')).toBeTruthy()
        expect(screen.queryByText('1-2')).toBeNull()
    })

    it('reports transient pointer and keyboard highlights independently of selection', () => {
        const hover = jest.fn()
        const select = jest.fn()
        render(<ProductUsageLegend {...props} onHoveredSeriesChange={hover} onSelectedSeriesChange={select} />)
        const product = screen.getByText('Product analytics')
        fireEvent.mouseEnter(product)
        expect(hover).toHaveBeenLastCalledWith('pa')
        fireEvent.mouseLeave(product)
        expect(hover).toHaveBeenLastCalledWith(null)
        fireEvent.focus(product)
        expect(hover).toHaveBeenLastCalledWith('pa')
        fireEvent.blur(product)
        expect(hover).toHaveBeenLastCalledWith(null)
        expect(select).not.toHaveBeenCalled()
    })
})
