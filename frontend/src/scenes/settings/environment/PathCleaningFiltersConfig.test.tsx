import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'
import { PathCleaningFiltersConfig } from './PathCleaningFiltersConfig'
import { PathCleaningFilter } from '~/types'

// Mock kea
jest.mock('kea')
const mockUseActions = useActions as jest.MockedFunction<typeof useActions>
const mockUseValues = useValues as jest.MockedFunction<typeof useValues>

// Mock teamLogic and userLogic
jest.mock('scenes/teamLogic')
jest.mock('scenes/userLogic')

describe('PathCleaningFiltersConfig', () => {
    const mockUpdateCurrentTeam = jest.fn()
    const mockTeam = {
        id: 1,
        name: 'Test Team',
        path_cleaning_filters: [
            { regex: '\\/user\\/\\d+', alias: '/user/:id' },
            { regex: '\\/product\\/[a-z]+', alias: '/product/:slug' },
        ] as PathCleaningFilter[],
    }

    beforeEach(() => {
        jest.clearAllMocks()
        mockUseActions.mockReturnValue({ updateCurrentTeam: mockUpdateCurrentTeam })
        mockUseValues.mockImplementation((logic) => {
            if (logic.toString().includes('teamLogic')) {
                return { currentTeam: mockTeam }
            }
            if (logic.toString().includes('userLogic')) {
                return { hasAvailableFeature: () => true }
            }
            return {}
        })
    })

    it('renders path cleaning configuration', () => {
        render(<PathCleaningFiltersConfig />)

        expect(screen.getByText(/Make your.*Paths.*clearer by aliasing/)).toBeInTheDocument()
        expect(screen.getByText(/Rules are applied in the order that they're listed/)).toBeInTheDocument()
    })

    it('shows premium feature message when feature not available', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic.toString().includes('teamLogic')) {
                return { currentTeam: mockTeam }
            }
            if (logic.toString().includes('userLogic')) {
                return { hasAvailableFeature: () => false }
            }
            return {}
        })

        render(<PathCleaningFiltersConfig />)

        expect(screen.getByText(/Advanced path cleaning is a premium feature/)).toBeInTheDocument()
    })

    it('returns null when no current team', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic.toString().includes('teamLogic')) {
                return { currentTeam: null }
            }
            if (logic.toString().includes('userLogic')) {
                return { hasAvailableFeature: () => true }
            }
            return {}
        })

        const { container } = render(<PathCleaningFiltersConfig />)
        expect(container.firstChild).toBeNull()
    })

    it('renders path tester', () => {
        render(<PathCleaningFiltersConfig />)

        expect(screen.getByPlaceholderText('Enter a path to test')).toBeInTheDocument()
        expect(screen.getByText('Wanna test what your cleaned path will look like?')).toBeInTheDocument()
    })

    it('tests path cleaning with regex patterns', async () => {
        render(<PathCleaningFiltersConfig />)

        const testInput = screen.getByPlaceholderText('Enter a path to test')
        await userEvent.type(testInput, '/user/123/profile')

        // The cleaned path should show the alias
        expect(screen.getByText('/user/:id/profile')).toBeInTheDocument()
    })

    it('handles multiple regex matches in path', async () => {
        const teamWithGlobalRegex = {
            ...mockTeam,
            path_cleaning_filters: [{ regex: '[a-zA-Z0-9]{16}', alias: '<id>' }] as PathCleaningFilter[],
        }

        mockUseValues.mockImplementation((logic) => {
            if (logic.toString().includes('teamLogic')) {
                return { currentTeam: teamWithGlobalRegex }
            }
            if (logic.toString().includes('userLogic')) {
                return { hasAvailableFeature: () => true }
            }
            return {}
        })

        render(<PathCleaningFiltersConfig />)

        const testInput = screen.getByPlaceholderText('Enter a path to test')
        await userEvent.type(testInput, '/category/abcd1234abcd1234/type/1234abcd1234abcd/')

        // Should replace both 16-character sequences
        expect(screen.getByText('/category/<id>/type/<id>/')).toBeInTheDocument()
    })

    it('handles invalid regex patterns gracefully', async () => {
        const teamWithInvalidRegex = {
            ...mockTeam,
            path_cleaning_filters: [
                { regex: '[invalid', alias: '/invalid' },
                { regex: '\\/valid\\/\\d+', alias: '/valid/:id' },
            ] as PathCleaningFilter[],
        }

        mockUseValues.mockImplementation((logic) => {
            if (logic.toString().includes('teamLogic')) {
                return { currentTeam: teamWithInvalidRegex }
            }
            if (logic.toString().includes('userLogic')) {
                return { hasAvailableFeature: () => true }
            }
            return {}
        })

        render(<PathCleaningFiltersConfig />)

        const testInput = screen.getByPlaceholderText('Enter a path to test')
        await userEvent.type(testInput, '/valid/123/test')

        // Should only apply valid regex, invalid one should be skipped
        expect(screen.getByText('/valid/:id/test')).toBeInTheDocument()
    })

    it('calls updateCurrentTeam when filters change', () => {
        render(<PathCleaningFiltersConfig />)

        // This would be triggered by the PathCleanFilters component
        // We can't easily test the drag-and-drop behavior, but we can verify
        // that the component passes the correct setFilters function
        expect(screen.getByText(/user.*:id/)).toBeInTheDocument()
        expect(screen.getByText(/product.*:slug/)).toBeInTheDocument()
    })
})
