import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { EditModeEdgeOverlay } from './EditModeEdgeOverlay'

describe('EditModeEdgeOverlay', () => {
    beforeEach(() => {
        cleanup()
    })

    it('renders four edge hit areas with data attr', () => {
        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={() => {}} />)

        const edges = getAllByTitle('Click to edit layout')
        expect(edges).toHaveLength(4)
        edges.forEach((edge) => {
            expect(edge).toHaveAttribute('data-attr', 'dashboard-edit-mode-from-card-edge')
        })
    })

    it.each([0, 1, 2, 3])('calls onEnterEditMode when edge %i is pressed', (edgeIndex) => {
        const onEnterEditMode = jest.fn()

        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={onEnterEditMode} />)
        const edges = getAllByTitle('Click to edit layout')

        fireEvent.mouseDown(edges[edgeIndex])
        expect(onEnterEditMode).toHaveBeenCalledTimes(1)
    })
})
