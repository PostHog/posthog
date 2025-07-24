import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PathCleanFilters } from './PathCleanFilters'
import { PathCleaningFilter } from '~/types'

const mockFilters: PathCleaningFilter[] = [
    { regex: '\\/user\\/\\d+', alias: '/user/:id' },
    { regex: '\\/product\\/[a-z]+', alias: '/product/:slug' },
    { regex: '\\?utm_.*', alias: '' },
]

describe('PathCleanFilters', () => {
    const renderComponent = (filters: PathCleaningFilter[] = [], setFilters = jest.fn()): any => {
        return render(<PathCleanFilters filters={filters} setFilters={setFilters} />)
    }

    it('displays empty state when no filters provided', () => {
        renderComponent()
        expect(
            screen.getByText('No path cleaning rules configured. Add your first rule to get started.')
        ).toBeInTheDocument()
    })

    it('renders filters in a table with correct order', () => {
        renderComponent(mockFilters)

        // Check that all filters are displayed
        expect(screen.getByText('/user/\\d+')).toBeInTheDocument()
        expect(screen.getByText('/product/[a-z]+')).toBeInTheDocument()
        expect(screen.getByText('\\?utm_.*')).toBeInTheDocument()

        // Check order numbers
        const orderCells = screen.getAllByText(/^[123]$/)
        expect(orderCells).toHaveLength(3)
        expect(orderCells[0]).toHaveTextContent('1')
        expect(orderCells[1]).toHaveTextContent('2')
        expect(orderCells[2]).toHaveTextContent('3')
    })

    it('shows regex and alias correctly', () => {
        renderComponent(mockFilters)

        // Check regex patterns
        expect(screen.getByText('/user/\\d+')).toBeInTheDocument()
        expect(screen.getByText('/product/[a-z]+')).toBeInTheDocument()

        // Check aliases
        expect(screen.getByText('/user/:id')).toBeInTheDocument()
        expect(screen.getByText('/product/:slug')).toBeInTheDocument()
    })

    it('calls setFilters when filter is removed', async () => {
        const setFilters = jest.fn()
        renderComponent(mockFilters, setFilters)

        const deleteButtons = screen.getAllByRole('button', { name: /delete rule/i })
        await userEvent.click(deleteButtons[0])

        expect(setFilters).toHaveBeenCalledWith([
            { regex: '\\/product\\/[a-z]+', alias: '/product/:slug' },
            { regex: '\\?utm_.*', alias: '' },
        ])
    })

    it('shows add button', () => {
        renderComponent()
        expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument()
    })

    it('handles invalid regex patterns', () => {
        const invalidFilters: PathCleaningFilter[] = [
            { regex: '[invalid', alias: '/invalid' },
            { regex: '\\/valid\\/\\d+', alias: '/valid/:id' },
        ]

        renderComponent(invalidFilters)

        // Invalid regex should be marked differently
        const invalidRegex = screen.getByText('[invalid')
        expect(invalidRegex).toHaveClass('text-danger')
    })

    it('shows drag handles for reordering', () => {
        renderComponent(mockFilters)

        const dragHandles = screen.getAllByRole('generic', { name: /drag/i })
        expect(dragHandles).toHaveLength(3)
    })

    it('renders aliases with dynamic parts highlighted', () => {
        const filtersWithDynamicParts: PathCleaningFilter[] = [
            { regex: '\\/user\\/\\d+', alias: '/user/<id>' },
            { regex: '\\/api\\/.*', alias: '/api/:endpoint' },
        ]

        renderComponent(filtersWithDynamicParts)

        // Check that dynamic parts are rendered with special styling
        expect(screen.getByText('<id>')).toBeInTheDocument()
        expect(screen.getByText(':endpoint')).toBeInTheDocument()
    })
})
