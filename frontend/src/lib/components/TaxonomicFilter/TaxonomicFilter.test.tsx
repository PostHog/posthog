import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from './types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicFilter', () => {
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

    function renderFilter(
        props: Partial<React.ComponentProps<typeof TaxonomicFilter>> = {}
    ): ReturnType<typeof render> & { onChange: jest.Mock } {
        const onChange = jest.fn()
        const result = render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={onChange}
                    {...props}
                />
            </Provider>
        )
        return { ...result, onChange }
    }

    it('renders search input and loads results from the API', async () => {
        renderFilter()

        expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })
    })

    it('typing in the search field filters results', async () => {
        renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })

        userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'test event')

        await waitFor(() => {
            expect(screen.getAllByText('test event').length).toBeGreaterThanOrEqual(1)
            expect(screen.queryByText('$click')).not.toBeInTheDocument()
        })
    })

    it('clicking a category tab switches the visible results', async () => {
        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
        })

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })

        userEvent.click(screen.getByTestId('taxonomic-tab-actions'))

        await waitFor(() => {
            expect(screen.getByText('Action with a moderately long name')).toBeInTheDocument()
        })
    })

    it('clicking a result calls onChange with the correct group, value, and item', async () => {
        const { onChange } = renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
        })

        userEvent.click(screen.getByTestId('prop-filter-events-1'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })
        const [group, value, item] = onChange.mock.calls[0]
        expect(group.type).toBe(TaxonomicFilterGroupType.Events)
        expect(value).toBe('event1')
        expect(item.name).toBe('event1')
    })

    it('keyboard-only: type to search, enter to select', async () => {
        const { onChange } = renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })

        userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), '$click')

        await waitFor(() => {
            expect(screen.getAllByText('$click').length).toBeGreaterThanOrEqual(1)
        })

        userEvent.keyboard('{Enter}')

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })
        expect(onChange.mock.calls[0][1]).toBe('$click')
    })
})
