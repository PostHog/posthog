import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { TextCard, TextContent } from './TextCard'

const makeTextTile = (
    overrides: Partial<DashboardTile<QueryBasedInsightModel>> = {}
): DashboardTile<QueryBasedInsightModel> =>
    ({
        id: 1,
        text: {
            body: 'text body',
            last_modified_at: '2022-04-01T12:24:36',
        },
        layouts: {},
        color: null,
        ...overrides,
    }) as DashboardTile<QueryBasedInsightModel>

describe('TextCard', () => {
    it('shows the more button when placement is not Public', () => {
        const { getByLabelText, getByText } = render(
            <TextCard
                textTile={makeTextTile()}
                placement={DashboardPlacement.Dashboard}
                moreButtonOverlay={<div>more overlay</div>}
            />
        )

        // click the visible more button (aria-label="more") and ensure overlay content appears
        fireEvent.click(getByLabelText('more'))
        expect(getByText('more overlay')).toBeInTheDocument()
    })

    it('renders edit-mode edge overlay when enabled and not resizing', () => {
        const onEnterEditModeFromEdge = jest.fn()

        const { getAllByTitle } = render(
            <TextCard
                textTile={makeTextTile()}
                placement={DashboardPlacement.Dashboard}
                canEnterEditModeFromEdge={true}
                onEnterEditModeFromEdge={onEnterEditModeFromEdge}
            />
        )

        const edges = getAllByTitle('Click to edit layout')
        expect(edges).toHaveLength(4)

        fireEvent.mouseDown(edges[0])
        expect(onEnterEditModeFromEdge).toHaveBeenCalledTimes(1)
    })

    describe('TextContent', () => {
        it('calls closeDetails when clicked', () => {
            const closeDetails = jest.fn()

            const { container } = render(
                <TextContent text="some **markdown**" closeDetails={closeDetails} className="custom-class" />
            )

            const paragraph = container.querySelector('p')
            expect(paragraph).not.toBeNull()
            fireEvent.click(paragraph as HTMLElement)
            expect(closeDetails).toHaveBeenCalledTimes(1)
        })
    })

    describe('resize handles', () => {
        it('shows all 8 handles when showResizeHandles is true', () => {
            const { container } = render(
                <TextCard textTile={makeTextTile()} placement={DashboardPlacement.Dashboard} showResizeHandles={true} />
            )

            const horizontalHandles = container.querySelectorAll('.handle.horizontal')
            const verticalHandles = container.querySelectorAll('.handle.vertical')
            const cornerHandles = container.querySelectorAll('.handle.corner')

            expect(horizontalHandles.length).toBe(2)
            expect(verticalHandles.length).toBe(2)
            expect(cornerHandles.length).toBe(4)
        })
    })
})
