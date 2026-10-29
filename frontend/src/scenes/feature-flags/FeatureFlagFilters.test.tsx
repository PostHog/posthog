import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FeatureFlagFiltersSection } from './FeatureFlagFilters'

const mockFilters = {
    search: '',
    page: 1,
}

const mockSetFilters = jest.fn()

describe('FeatureFlagFiltersSection', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('shows no filters by default when no config is provided', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows no filters by default when empty config is provided', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{}}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows only search filter when search is enabled', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search feature flags"
                filtersConfig={{ search: true }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows only type filter when type is enabled', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{ type: true }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows only status filter when status is enabled', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{ status: true }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows only createdBy filter when createdBy is enabled', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{ createdBy: true }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows multiple filters when multiple are configured', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{ search: true, type: true, status: true }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })

    it('shows all filters when all are enabled', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{
                    search: true,
                    type: true,
                    status: true,
                    createdBy: true,
                    runtime: true,
                }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).toBeInTheDocument()
    })

    it('switches to the deleted view and drops the other status filters', async () => {
        render(
            <FeatureFlagFiltersSection
                filters={{ ...mockFilters, archived: 'true', active: 'false' }}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{ status: true }}
            />
        )

        await userEvent.click(screen.getByRole('button', { name: 'Archived' }))
        await userEvent.click(screen.getByRole('menuitem', { name: 'Deleted' }))

        expect(mockSetFilters).toHaveBeenCalledWith({ search: '', deleted: 'true', page: 1 }, true)
    })

    it('ignores false values in config', () => {
        const { container } = render(
            <FeatureFlagFiltersSection
                filters={mockFilters}
                setFeatureFlagsFilters={mockSetFilters}
                searchPlaceholder="Search"
                filtersConfig={{
                    search: true,
                    type: false,
                    status: false,
                    createdBy: true,
                    runtime: false,
                }}
            />
        )

        expect(container.querySelector('[data-attr="feature-flag-search"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-type"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-status"]')).not.toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-created-by"]')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="feature-flag-select-runtime"]')).not.toBeInTheDocument()
    })
})
