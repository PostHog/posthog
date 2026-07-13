import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { RecordingsUniversalFilterAddFilterPopover } from './RecordingsUniversalFiltersEmbed'

const DEFAULT_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('RecordingsUniversalFilterAddFilterPopover (pill category dropdown)', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/environments/:team/persons/properties': [],
                '/api/environments/:team/events/values': [],
                '/api/environments/:team/persons/values': [],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderPopover(): void {
        const taxonomicGroupTypes = [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
        ]
        render(
            <Provider>
                <UniversalFilters
                    rootKey="replay-add-filter-pill-test"
                    group={DEFAULT_GROUP}
                    onChange={jest.fn()}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                >
                    <RecordingsUniversalFilterAddFilterPopover
                        categoryDropdownVariant="pill"
                        taxonomicGroupTypes={taxonomicGroupTypes}
                    />
                </UniversalFilters>
            </Provider>
        )
    }

    it('applies the picked category from the pill menu while keeping the filter open', async () => {
        renderPopover()

        // Open the replay filter — focusing the search input reveals the category pill.
        const input = screen.getByTestId('replay-filters-add-filter-input')
        await userEvent.click(input)

        const pillTrigger = await screen.findByTestId('taxonomic-category-dropdown-trigger-pill')
        // Defaults to the first group.
        expect(pillTrigger).toHaveTextContent('Events')

        // Type a query so we can prove the surrounding popover is not dismissed by the pick:
        // the bug routed the menu click through the parent popover's outside-press handler,
        // which cleared the query and collapsed the filter.
        fireEvent.change(input, { target: { value: 'email' } })
        expect(input).toHaveValue('email')

        // Open the pill menu and select a visible option. Re-query the trigger — typing
        // re-renders the input suffix, detaching the node captured above.
        await userEvent.click(screen.getByTestId('taxonomic-category-dropdown-trigger-pill'))
        const personPropertiesItem = await screen.findByTestId('taxonomic-category-dropdown-item-person_properties')
        await userEvent.click(personPropertiesItem)

        // The picked category is applied (findByRole waits for the re-render)...
        expect(
            await screen.findByRole('button', { name: 'Current category: Person properties. Click to change.' })
        ).toBeInTheDocument()

        // ...and the main filter stays open with its search query intact.
        expect(screen.getByTestId('replay-filters-add-filter-input')).toBeInTheDocument()
        expect(screen.getByTestId('replay-filters-add-filter-input')).toHaveValue('email')
    })
})
