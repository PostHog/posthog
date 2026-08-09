import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { TaxonomicFilterGroupType } from '../../TaxonomicFilter/types'
import { PropertyFilters } from '../PropertyFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// PropertyFilters is the second consumer wrapper that opts into the rebuilt menu
// (the first being TaxonomicPopover). Property filters render inside `More` /
// LemonMenu overlays across the app, with `disablePopover` set because the menu
// supplies the popover. That is the same "nested picker dismisses its parent
// overlay" shape as the OP's "Add column" bug, on a different surface: the menu
// portals out of the enclosing overlay, so without the fix a click inside it
// reads as "outside" and closes the overlay before the selection can commit.
describe('TaxonomicPropertyFilter nested inside a More dropdown', () => {
    let unmountFeatureFlagLogic: (() => void) | null = null

    beforeEach(() => {
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [] },
                '/api/environments/:team/persons/properties': [],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        unmountFeatureFlagLogic = featureFlagLogic.mount()
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        unmountFeatureFlagLogic?.()
        unmountFeatureFlagLogic = null
        cleanup()
    })

    it('commits a picked property from inside the enclosing overlay', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true,
        })
        const onChange = jest.fn()
        render(
            <Provider>
                <More
                    overlay={
                        <PropertyFilters
                            pageKey="nested-property-filter"
                            propertyFilters={[]}
                            onChange={onChange}
                            sendAllKeyUpdates
                            disablePopover
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.PersonProperties,
                            ]}
                        />
                    }
                />
            </Provider>
        )

        await userEvent.click(screen.getByLabelText('more'))
        await userEvent.click(await screen.findByTestId('taxonomic-popover-menu-trigger'))

        await userEvent.click(await screen.findByTestId('taxonomic-filter-menu-new'))
        await waitFor(() => expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument())
        await userEvent.type(screen.getByTestId('menu-filter-search'), 'purchase_value')

        // Name and value cells both render the property, so target the row.
        const cell = (await screen.findAllByText('purchase_value'))[0]
        const row = cell.closest('[data-slot="taxonomic-filter-menu-row"]')
        await userEvent.click(row as HTMLElement)

        await waitFor(() => expect(onChange).toHaveBeenCalled())
        const filters = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(filters[0].key).toBe('purchase_value')
        expect(filters[0].type).toBe('event')
    })
})
