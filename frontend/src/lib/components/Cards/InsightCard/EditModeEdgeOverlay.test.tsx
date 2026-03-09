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

    it('calls onEnterEditMode when an edge is pressed', () => {
        const onEnterEditMode = jest.fn()

        const { getAllByTitle } = render(<EditModeEdgeOverlay onEnterEditMode={onEnterEditMode} />)
        const [firstEdge] = getAllByTitle('Click to edit layout')

        fireEvent.mouseDown(firstEdge)
        expect(onEnterEditMode).toHaveBeenCalled()
    })
})
