import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { PropertyFilters } from './PropertyFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('PropertyFilters', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [
                    { id: 1, name: 'location', count: 1 },
                    { id: 2, name: 'role', count: 2 },
                ],
                '/api/environments/:team/events/values': [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderPropertyFilters(
        props: Partial<React.ComponentProps<typeof PropertyFilters>> = {}
    ): ReturnType<typeof render> & { onChange: jest.Mock } {
        const onChange = jest.fn()
        const result = render(
            <Provider>
                <PropertyFilters
                    pageKey="test-page"
                    onChange={onChange}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                    {...props}
                />
            </Provider>
        )
        return { ...result, onChange }
    }

    const BROWSER_FILTER = {
        key: '$browser',
        type: PropertyFilterType.Event,
        value: 'Chrome',
        operator: PropertyOperator.Exact,
    } as const

    const OS_FILTER = {
        key: '$os',
        type: PropertyFilterType.Event,
        value: 'Mac',
        operator: PropertyOperator.Exact,
    } as const

    it('add filter: click add, search, select property, verify onChange shape', async () => {
        const { onChange } = renderPropertyFilters({ sendAllKeyUpdates: true })

        userEvent.click(screen.getByTestId('new-prop-filter-test-page'))

        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })

        userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), '$browser')

        await waitFor(() => {
            expect(screen.getAllByText('$browser').length).toBeGreaterThanOrEqual(1)
        })

        userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalled()
        })
        const filters = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(filters[0].key).toBe('$browser')
        expect(filters[0].type).toBe('event')
    })

    it('remove first of two filters: onChange has only the remaining filter', async () => {
        const { onChange } = renderPropertyFilters({
            propertyFilters: [BROWSER_FILTER, OS_FILTER],
        })

        expect(screen.getByText(/Chrome/)).toBeInTheDocument()
        expect(screen.getByText(/Mac/)).toBeInTheDocument()

        const firstRow = screen.getByTestId('property-filter-0')
        const closeButton = firstRow.querySelector('.PropertyFilterButton--closeable .LemonButton')
        userEvent.click(closeButton!)

        await waitFor(() => {
            expect(onChange).toHaveBeenCalled()
        })

        const remaining = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(remaining).toHaveLength(1)
        expect(remaining[0].key).toBe('$os')
        expect(remaining[0].value).toBe('Mac')
    })

    it('round-trip: onChange output fed back as props renders correctly', async () => {
        const onChange = jest.fn()
        const { rerender } = render(
            <Provider>
                <PropertyFilters
                    pageKey="round-trip"
                    onChange={onChange}
                    propertyFilters={[]}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    sendAllKeyUpdates={true}
                />
            </Provider>
        )

        userEvent.click(screen.getByTestId('new-prop-filter-round-trip'))
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })

        userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), '$browser')
        await waitFor(() => {
            expect(screen.getAllByText('$browser').length).toBeGreaterThanOrEqual(1)
        })

        userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))
        await waitFor(() => {
            expect(onChange).toHaveBeenCalled()
        })

        // Feed onChange output back as props (simulates real parent component behavior)
        const outputFilters = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        rerender(
            <Provider>
                <PropertyFilters
                    pageKey="round-trip"
                    onChange={onChange}
                    propertyFilters={outputFilters}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    sendAllKeyUpdates={true}
                />
            </Provider>
        )

        const pill = screen.getByTestId('property-filter-0').querySelector('.PropertyFilterButton-content')
        expect(pill?.textContent).toMatch(/Browser/)
    })

    it('does not change reducer state when re-rendered with same filter values', () => {
        const filters = [BROWSER_FILTER]
        const onChange = jest.fn()

        const { rerender } = render(
            <Provider>
                <PropertyFilters
                    pageKey="test-rerender"
                    onChange={onChange}
                    propertyFilters={[...filters]}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                />
            </Provider>
        )

        expect(screen.getByTestId('property-filter-0')).toBeInTheDocument()

        const { propertyFilterLogic } = require('./propertyFilterLogic')
        const logic = propertyFilterLogic({ pageKey: 'test-rerender', onChange, sendAllKeyUpdates: false })
        const stateBefore = logic.values._filtersState

        rerender(
            <Provider>
                <PropertyFilters
                    pageKey="test-rerender"
                    onChange={onChange}
                    propertyFilters={[...filters]}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                />
            </Provider>
        )

        expect(logic.values._filtersState).toBe(stateBefore)
        expect(screen.getByTestId('property-filter-0')).toBeInTheDocument()
    })
})
