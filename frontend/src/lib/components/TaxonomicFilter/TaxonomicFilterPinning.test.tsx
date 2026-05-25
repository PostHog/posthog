import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { TaxonomicFilter } from './TaxonomicFilter'
import { taxonomicFilterPinnedPropertiesLogic } from './taxonomicFilterPinnedPropertiesLogic'
import { TaxonomicFilterGroupType } from './types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicFilter pinning', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [] },
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
    ): ReturnType<typeof render> {
        return render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                    onChange={jest.fn()}
                    {...props}
                />
            </Provider>
        )
    }

    it('shows a Pinned tab when there are pinned items', async () => {
        const logic = taxonomicFilterPinnedPropertiesLogic.build()
        logic.mount()
        logic.actions.togglePin(TaxonomicFilterGroupType.PersonProperties, 'Person properties', 'location', {
            name: 'location',
        })

        renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-tab-pinned_filters')).toBeInTheDocument()
        })

        logic.unmount()
    })

    it('renders pinned items in the Pinned tab', async () => {
        const logic = taxonomicFilterPinnedPropertiesLogic.build()
        logic.mount()
        logic.actions.togglePin(TaxonomicFilterGroupType.PersonProperties, 'Person properties', 'location', {
            name: 'location',
        })

        renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-tab-pinned_filters')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByTestId('taxonomic-tab-pinned_filters'))

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-pinned_filters-0')).toBeInTheDocument()
        })

        logic.unmount()
    })

    it('shows Pinned tab with zero count when no items are pinned', async () => {
        renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-tab-event_properties')).toBeInTheDocument()
        })

        const pinnedTab = screen.getByTestId('taxonomic-tab-pinned_filters')
        expect(pinnedTab).toBeInTheDocument()
        expect(pinnedTab.textContent).toContain('0')
    })

    it('shows pin button in definition popover on hover', async () => {
        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            popoverEnabled: true,
        })

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-event_properties-0')).toBeInTheDocument()
        })

        await userEvent.hover(screen.getByTestId('prop-filter-event_properties-0'))

        await waitFor(() => {
            const pinButtons = screen.queryAllByRole('button', { name: /pin/i })
            expect(pinButtons.length).toBeGreaterThan(0)
        })
    })

    it.each([
        {
            description: 'fresh person pin with full distinct_ids',
            value: 'distinct-abc',
            storedItem: { name: 'Alice', distinct_ids: ['distinct-abc'] },
        },
        {
            description: 'pre-existing pin shrunk to just { name } (old localStorage shape)',
            value: 'distinct-abc',
            storedItem: { name: 'distinct-abc' },
        },
    ])('does not crash when hovering a pinned Person item: $description', async ({ value, storedItem }) => {
        const logic = taxonomicFilterPinnedPropertiesLogic.build()
        logic.mount()
        // Seed the persisted shape directly so we can exercise both the new (full)
        // and the old ({ name }-only) localStorage entry shapes.
        logic.actions.setPinnedFilters([
            {
                groupType: TaxonomicFilterGroupType.Persons,
                groupName: 'Persons',
                value,
                item: storedItem,
                timestamp: Date.now(),
            },
        ])

        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Persons],
            popoverEnabled: true,
        })

        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-tab-pinned_filters')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByTestId('taxonomic-tab-pinned_filters'))

        const pinnedRow = await screen.findByTestId('prop-filter-pinned_filters-0')

        // Hovering the row triggers ControlledDefinitionPopover, which calls the
        // source group's getValue on the stored item. Before the fix, the old
        // `{ name }`-only shape threw `TypeError: Cannot read properties of
        // undefined (reading '0')` here because Persons read `distinct_ids[0]`.
        // Awaiting the async hover ensures any rejection from a synchronous
        // render throw fails the test, and the positive `Person` popover-header
        // assertion proves the chain ran to completion — not just "didn't throw".
        await userEvent.hover(pinnedRow)
        expect(await screen.findByText('Person')).toBeInTheDocument()

        logic.unmount()
    })
})
