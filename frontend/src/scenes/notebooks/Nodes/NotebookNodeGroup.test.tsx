import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Group } from '~/types'

import { DataSourceIcon, GroupInfo, LifetimeValue, MRR } from './NotebookNodeGroup'

// Mock NodeWrapper to avoid circular dependencies
jest.mock('./NodeWrapper', () => ({
    createPostHogWidgetNode: () => ({}),
}))

// Mocking because it is annoying to mock the hover to assert the tooltip text
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    Tooltip: ({ children, title }: { children: React.ReactNode; title: string }) => (
        <div data-attr={title}>{children}</div>
    ),
}))

// Mock the utility functions
jest.mock('./utils', () => ({
    calculateMRRData: (groupData: Group) => {
        const mrr = groupData.group_properties?.mrr
        if (typeof mrr === 'number') {
            return {
                mrr,
                forecastedMrr: null,
                percentageDiff: 10,
                tooltipText: 'MRR trend up 10%',
                trendDirection: 'up' as const,
            }
        }
        return null
    },
    getPaidProducts: (groupData: Group) => {
        return groupData.group_properties?.paid_products || []
    },
}))

describe('DataSourceIcon', () => {
    afterEach(() => {
        cleanup()
    })

    it('should render piggybank icon for revenue-analytics source', async () => {
        render(<DataSourceIcon source="revenue-analytics" />)

        expect(screen.getByTestId('piggybank-icon')).toHaveClass('w-3 h-3 text-muted')
        expect(screen.getByTestId('piggybank-icon')).toBeInTheDocument()
        expect(screen.getByTestId('From Revenue analytics')).toBeInTheDocument()
    })

    it('should render database icon for properties source', () => {
        render(<DataSourceIcon source="properties" />)

        expect(screen.getByTestId('database-icon')).toBeInTheDocument()
        expect(screen.getByTestId('database-icon')).toHaveClass('w-3 h-3 text-muted')
        expect(screen.getByTestId('From group properties')).toBeInTheDocument()
    })

    it('should render nothing for null source', () => {
        const { container } = render(<DataSourceIcon source={null} />)

        expect(container.firstChild).toBeNull()
    })
})

describe('MRR Component', () => {
    afterEach(() => {
        cleanup()
    })

    const mockGroupData: Group = {
        group_key: 'test-group',
        group_type_index: 0,
        group_properties: {
            mrr: 1500,
        },
        created_at: '2023-01-01T00:00:00Z',
    } as unknown as Group

    const baseCurrency: CurrencyCode = CurrencyCode.USD

    it('should display MRR value with revenue analytics source icon', () => {
        const mrrData = { value: 2000, source: 'revenue-analytics' as const }

        render(<MRR groupData={mockGroupData} mrr={mrrData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('MRR:')).toBeInTheDocument()
        expect(screen.getByText('$2,000.00')).toBeInTheDocument()
        expect(screen.getByTestId('piggybank-icon')).toBeInTheDocument()
        expect(screen.queryByTestId('database-icon')).not.toBeInTheDocument()
    })

    it('should display MRR value with properties source icon and trend', () => {
        const mrrData = { value: 1500, source: 'properties' as const }

        render(<MRR groupData={mockGroupData} mrr={mrrData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('MRR:')).toBeInTheDocument()
        expect(screen.getByText('$1,500.00')).toBeInTheDocument()
        expect(screen.getByTestId('database-icon')).toBeInTheDocument()
        expect(screen.getByTestId('trending-icon')).toBeInTheDocument() // Trend from properties
        expect(screen.queryByTestId('piggybank-icon')).not.toBeInTheDocument()
    })

    it('should display loading skeleton when loading', () => {
        const mrrData = { value: 1500, source: 'properties' as const }

        const { container } = render(
            <MRR groupData={mockGroupData} mrr={mrrData} baseCurrency={baseCurrency} isLoading={true} />
        )

        const skeleton = container.querySelector('.LemonSkeleton')
        expect(skeleton).toBeInTheDocument()
        expect(skeleton).toHaveClass('h-4', 'w-32')
        expect(screen.queryByText('MRR:')).not.toBeInTheDocument()
    })

    it('should return null when no MRR data is available', () => {
        const mrrData = { value: null, source: null }

        const { container } = render(
            <MRR groupData={mockGroupData} mrr={mrrData} baseCurrency={baseCurrency} isLoading={false} />
        )

        expect(container.firstChild).toBeNull()
    })

    it('should not show source icons when source is null', () => {
        const mrrData = { value: 1500, source: null }

        render(<MRR groupData={mockGroupData} mrr={mrrData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('$1,500.00')).toBeInTheDocument()
        expect(screen.queryByTestId('piggybank-icon')).not.toBeInTheDocument()
        expect(screen.queryByTestId('database-icon')).not.toBeInTheDocument()
    })
})

describe('LifetimeValue Component', () => {
    afterEach(() => {
        cleanup()
    })

    const baseCurrency: CurrencyCode = CurrencyCode.USD

    it('should display lifetime value with revenue analytics source icon', () => {
        const lifetimeValueData = { value: 15000, source: 'revenue-analytics' as const }

        render(<LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('Lifetime value:')).toBeInTheDocument()
        expect(screen.getByText('$15,000.00')).toBeInTheDocument()
        expect(screen.getByTestId('piggybank-icon')).toBeInTheDocument()
        expect(screen.queryByTestId('database-icon')).not.toBeInTheDocument()
    })

    it('should display lifetime value with properties source icon', () => {
        const lifetimeValueData = { value: 25000, source: 'properties' as const }

        render(<LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('Lifetime value:')).toBeInTheDocument()
        expect(screen.getByText('$25,000.00')).toBeInTheDocument()
        expect(screen.getByTestId('database-icon')).toBeInTheDocument()
        expect(screen.queryByTestId('piggybank-icon')).not.toBeInTheDocument()
    })

    it('should display loading skeleton when loading', () => {
        const lifetimeValueData = { value: 15000, source: 'properties' as const }

        const { container } = render(
            <LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={true} />
        )

        const skeleton = container.querySelector('.LemonSkeleton')
        expect(skeleton).toBeInTheDocument()
        expect(skeleton).toHaveClass('h-4', 'w-40')
        expect(screen.queryByText('Lifetime value:')).not.toBeInTheDocument()
    })

    it('should return null when lifetime value is null', () => {
        const lifetimeValueData = { value: null, source: null }

        const { container } = render(
            <LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={false} />
        )

        expect(container.firstChild).toBeNull()
    })

    it('should not show source icons when source is null', () => {
        const lifetimeValueData = { value: 15000, source: null }

        render(<LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(screen.getByText('$15,000.00')).toBeInTheDocument()
        expect(screen.queryByTestId('piggybank-icon')).not.toBeInTheDocument()
        expect(screen.queryByTestId('database-icon')).not.toBeInTheDocument()
    })

    it('should show correct tooltip text', () => {
        const lifetimeValueData = { value: 15000, source: 'revenue-analytics' as const }

        render(<LifetimeValue lifetimeValue={lifetimeValueData} baseCurrency={baseCurrency} isLoading={false} />)

        expect(
            screen.getByTestId('Total worth of revenue from this customer over the whole relationship')
        ).toBeInTheDocument()
    })
})

describe('GroupInfo Component', () => {
    afterEach(() => {
        cleanup()
    })

    const mockGroupData: Group = {
        group_key: 'test-group',
        group_type_index: 0,
        group_properties: {
            name: 'Test Company',
        },
        created_at: '2023-01-01T00:00:00Z',
    } as unknown as Group

    beforeEach(() => {
        // Set up API mocks for teamLogic
        useMocks({
            get: {
                '/api/projects/@current': () => [
                    200,
                    {
                        id: 1,
                        name: 'Test Project',
                        currency: CurrencyCode.USD,
                        revenue_analytics_config: {
                            base_currency: CurrencyCode.USD,
                        },
                    },
                ],
            },
        })

        // Initialize kea tests properly
        initKeaTests()
    })

    it('should render all components with mixed data sources', () => {
        const mrrData = { value: 2000, source: 'revenue-analytics' as const }
        const lifetimeValueData = { value: 15000, source: 'properties' as const }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.getByText('First seen:')).toBeInTheDocument()
        expect(screen.getByText('MRR:')).toBeInTheDocument()
        expect(screen.getByText('$2,000.00')).toBeInTheDocument()
        expect(screen.getByText('Lifetime value:')).toBeInTheDocument()
        expect(screen.getByText('$15,000.00')).toBeInTheDocument()

        // Should show both types of source icons
        const piggybankIcons = screen.getAllByTestId('piggybank-icon')
        const databaseIcons = screen.getAllByTestId('database-icon')
        expect(piggybankIcons).toHaveLength(1) // MRR from analytics
        expect(databaseIcons).toHaveLength(1) // LTV from properties
    })

    it('should handle mixed loading states', () => {
        const mrrData = { value: 2000, source: 'revenue-analytics' as const }
        const lifetimeValueData = { value: 15000, source: 'properties' as const }

        const { container } = render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={true}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        const skeletons = container.querySelectorAll('.LemonSkeleton')
        expect(skeletons).toHaveLength(1) // Only MRR skeleton
        expect(screen.getByText('Lifetime value:')).toBeInTheDocument() // LTV should render
    })

    it('should render when only MRR is available', () => {
        mockGroupData.group_properties = { mrr: 1500 }
        const mrrData = { value: 1500, source: 'properties' as const }
        const lifetimeValueData = { value: null, source: null }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.getByText('MRR:')).toBeInTheDocument()
        expect(screen.getByText('$1,500.00')).toBeInTheDocument()
        expect(screen.queryByText('Lifetime value:')).not.toBeInTheDocument()
    })

    it('should render when only lifetime value is available', () => {
        const mrrData = { value: null, source: null }
        const lifetimeValueData = { value: 25000, source: 'revenue-analytics' as const }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.queryByText('MRR:')).not.toBeInTheDocument()
        expect(screen.getByText('Lifetime value:')).toBeInTheDocument()
        expect(screen.getByText('$25,000.00')).toBeInTheDocument()
    })

    it('should render with no revenue data', () => {
        const mrrData = { value: null, source: null }
        const lifetimeValueData = { value: null, source: null }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.getByText('First seen:')).toBeInTheDocument()
        expect(screen.queryByText('MRR:')).not.toBeInTheDocument()
        expect(screen.queryByText('Lifetime value:')).not.toBeInTheDocument()
    })

    it('should show loading skeletons for both metrics when loading', () => {
        const mrrData = { value: 2000, source: 'revenue-analytics' as const }
        const lifetimeValueData = { value: 15000, source: 'properties' as const }

        const { container } = render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={true}
                    isLifetimeValueLoading={true}
                />
            </Provider>
        )

        const skeletons = container.querySelectorAll('.LemonSkeleton')
        expect(skeletons).toHaveLength(2) // Both MRR and LTV skeletons
    })
})

describe('Integration scenarios', () => {
    afterEach(() => {
        cleanup()
    })

    const mockGroupData: Group = {
        group_key: 'test-group',
        group_type_index: 0,
        group_properties: {
            name: 'Test Company',
            mrr: 1000,
            customer_lifetime_value: 20000,
            paid_products: ['Product A', 'Product B'],
        },
        created_at: '2023-01-01T00:00:00Z',
    } as unknown as Group

    beforeEach(() => {
        // Set up API mocks for teamLogic with EUR currency
        useMocks({
            get: {
                '/api/projects/@current': () => [
                    200,
                    {
                        id: 1,
                        name: 'Test Project',
                        currency: CurrencyCode.EUR,
                        revenue_analytics_config: {
                            base_currency: CurrencyCode.EUR,
                        },
                    },
                ],
            },
        })

        initKeaTests()
    })

    it('should handle different currency formatting', () => {
        const mrrData = { value: 2500, source: 'revenue-analytics' as const }
        const lifetimeValueData = { value: 30000, source: 'properties' as const }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        // Values should be formatted correctly
        expect(screen.getByText('$2,500.00')).toBeInTheDocument()
        expect(screen.getByText('$30,000.00')).toBeInTheDocument()
    })

    it('should show correct source indicators for fallback scenario', () => {
        // Simulate scenario where analytics failed and fell back to properties
        const mrrData = { value: 1000, source: 'properties' as const }
        const lifetimeValueData = { value: 20000, source: 'properties' as const }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        // Both should show database icons (properties source)
        const databaseIcons = screen.getAllByTestId('database-icon')
        expect(databaseIcons).toHaveLength(2)
        expect(screen.queryByTestId('piggybank-icon')).not.toBeInTheDocument()
    })

    it('should handle zero values correctly', () => {
        const mrrData = { value: 0, source: 'revenue-analytics' as const }
        const lifetimeValueData = { value: 0, source: 'revenue-analytics' as const }

        render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.getAllByText('$0.00')).toHaveLength(2)
    })

    it('should display paid products', () => {
        const mrrData = { value: 1000, source: 'properties' as const }
        const lifetimeValueData = { value: 20000, source: 'properties' as const }

        const { container } = render(
            <Provider>
                <GroupInfo
                    groupData={mockGroupData}
                    mrr={mrrData}
                    lifetimeValue={lifetimeValueData}
                    isMRRLoading={false}
                    isLifetimeValueLoading={false}
                />
            </Provider>
        )

        expect(screen.getByText('Paid products:')).toBeInTheDocument()
        const tags = container.querySelectorAll('.LemonTag')
        expect(tags).toHaveLength(2)
        expect(screen.getByText('Product A')).toBeInTheDocument()
        expect(screen.getByText('Product B')).toBeInTheDocument()
    })
})
