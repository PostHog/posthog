import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { EditModeEdgeOverlay } from './EditModeEdgeOverlay'

describe('EditModeEdgeOverlay', () => {
    beforeEach(() => {
        cleanup()
    })

    it('renders eight edge and corner hit areas with data attr', () => {
        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)

        const zones = getAllByTitle('Click to edit layout')
        expect(zones).toHaveLength(8)
        zones.forEach((zone) => {
            expect(zone).toHaveAttribute('data-attr', 'dashboard-edit-mode-from-card-edge')
        })
    })

    it.each([
        [0, 'n'],
        [1, 's'],
        [2, 'w'],
        [3, 'e'],
        [4, 'nw'],
        [5, 'ne'],
        [6, 'sw'],
        [7, 'se'],
    ])('calls onEnterEditMode with the pressed direction when zone %i is pressed', (zoneIndex, expectedEdge) => {
        const onEnterEditMode = jest.fn()

        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={onEnterEditMode} />)
        const zones = getAllByTitle('Click to edit layout')

        fireEvent.mouseDown(zones[zoneIndex])
        expect(onEnterEditMode).toHaveBeenCalledTimes(1)
        expect(onEnterEditMode).toHaveBeenCalledWith(expect.anything(), expectedEdge)
    })

    it('reveals all resize handles while any zone is hovered', () => {
        const { container, getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)
        const zones = getAllByTitle('Click to edit layout')

        expect(container.querySelectorAll('.handle')).toHaveLength(0)

        fireEvent.mouseEnter(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(8)

        fireEvent.mouseLeave(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(0)
    })

    it('keeps handles shown while moving between overlapping zones', () => {
        const { container, getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)
        const zones = getAllByTitle('Click to edit layout')

        // Enter a corner, then the adjacent edge, before leaving the corner — count must not hit zero.
        fireEvent.mouseEnter(zones[0])
        fireEvent.mouseEnter(zones[4])
        fireEvent.mouseLeave(zones[0])
        expect(container.querySelectorAll('.handle')).toHaveLength(8)
    })
})
