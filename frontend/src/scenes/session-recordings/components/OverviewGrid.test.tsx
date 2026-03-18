import { fireEvent, render } from '@testing-library/react'

import { OverviewGridItem } from './OverviewGrid'

describe('OverviewGridItem', () => {
    describe('filter button', () => {
        it('renders filter button when showFilter=true and onFilterClick provided', () => {
            const mockFilterClick = jest.fn()
            const { container } = render(
                <OverviewGridItem
                    description="Browser description"
                    label="Browser"
                    showFilter={true}
                    onFilterClick={mockFilterClick}
                >
                    Chrome
                </OverviewGridItem>
            )

            // Should render filter button (will fail until implemented)
            const filterButton = container.querySelector('[data-testid="filter-button"]')
            expect(filterButton).toBeTruthy()
        })

        it('does not render filter button when showFilter=false', () => {
            const mockFilterClick = jest.fn()
            const { container } = render(
                <OverviewGridItem
                    description="Browser description"
                    label="Browser"
                    showFilter={false}
                    onFilterClick={mockFilterClick}
                >
                    Chrome
                </OverviewGridItem>
            )

            const filterButton = container.querySelector('[data-testid="filter-button"]')
            expect(filterButton).toBeNull()
        })

        it('does not render filter button when onFilterClick not provided', () => {
            const { container } = render(
                <OverviewGridItem description="Browser description" label="Browser" showFilter={true}>
                    Chrome
                </OverviewGridItem>
            )

            const filterButton = container.querySelector('[data-testid="filter-button"]')
            expect(filterButton).toBeNull()
        })

        it('calls onFilterClick when filter button clicked', () => {
            const mockFilterClick = jest.fn()
            const { container } = render(
                <OverviewGridItem
                    description="Browser description"
                    label="Browser"
                    showFilter={true}
                    onFilterClick={mockFilterClick}
                >
                    Chrome
                </OverviewGridItem>
            )

            const filterButton = container.querySelector('[data-testid="filter-button"]')
            expect(filterButton).toBeTruthy()

            if (filterButton) {
                fireEvent.click(filterButton)
                expect(mockFilterClick).toHaveBeenCalledTimes(1)
            }
        })

        it('stops event propagation when filter button clicked', () => {
            const mockParentClick = jest.fn()
            const mockFilterClick = jest.fn()

            const { container } = render(
                <div onClick={mockParentClick}>
                    <OverviewGridItem
                        description="Browser description"
                        label="Browser"
                        showFilter={true}
                        onFilterClick={mockFilterClick}
                    >
                        Chrome
                    </OverviewGridItem>
                </div>
            )

            const filterButton = container.querySelector('[data-testid="filter-button"]')
            expect(filterButton).toBeTruthy()

            if (filterButton) {
                fireEvent.click(filterButton)
                expect(mockFilterClick).toHaveBeenCalledTimes(1)
                expect(mockParentClick).not.toHaveBeenCalled()
            }
        })
    })
})
