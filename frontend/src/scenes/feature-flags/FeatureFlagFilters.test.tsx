import '@testing-library/jest-dom'
import { render } from '@testing-library/react'

import { FeatureFlagFiltersSection } from './FeatureFlagFilters'

jest.mock('lib/logic/featureFlagLogic', () => ({
    featureFlagLogic: {
        values: {
            featureFlags: {},
        },
    },
}))

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
