import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import UniversalFilters from './UniversalFilters'

const mockTaxonomicFilterProps = jest.fn()

// Stub the taxonomic picker to read the props it gets without pinning its list internals or API calls.
jest.mock('../TaxonomicFilter/TaxonomicFilter', () => {
    const React = require('react')
    return {
        TaxonomicFilter: (props: Record<string, unknown>): JSX.Element => {
            mockTaxonomicFilterProps(props)
            return React.createElement('div', null, 'mock taxonomic filter')
        },
    }
})

describe('UniversalFilters endpoint filters', () => {
    const group: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [] }
    const endpointFilters = { metricName: 'http_requests', dateFrom: '2026-01-01T00:00:00Z' }

    beforeEach(() => {
        initKeaTests()
        mockTaxonomicFilterProps.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            picker: 'AddFilterButton',
            children: <UniversalFilters.AddFilterButton />,
            open: (): Promise<void> => userEvent.click(screen.getByText('Add filter')),
        },
        {
            picker: 'PureTaxonomicFilter',
            children: <UniversalFilters.PureTaxonomicFilter onChange={jest.fn()} />,
            open: (): Promise<void> => Promise.resolve(),
        },
    ])('$picker passes endpoint filters to the taxonomic filter', async ({ children, open }) => {
        render(
            <Provider>
                <UniversalFilters
                    rootKey="endpoint-filters-test"
                    group={group}
                    onChange={jest.fn()}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
                    endpointFilters={endpointFilters}
                >
                    {children}
                </UniversalFilters>
            </Provider>
        )
        await open()

        expect(screen.getByText('mock taxonomic filter')).toBeInTheDocument()
        expect(mockTaxonomicFilterProps).toHaveBeenLastCalledWith(expect.objectContaining({ endpointFilters }))
    })
})
