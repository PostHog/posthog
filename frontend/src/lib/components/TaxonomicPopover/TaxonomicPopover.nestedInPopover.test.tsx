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

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { TaxonomicPopover } from './TaxonomicPopover'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// The exact group types DataTable's "Add column left/right" pickers pass.
const ADD_COLUMN_GROUP_TYPES = [
    TaxonomicFilterGroupType.HogQLExpression,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

describe('TaxonomicPopover nested inside a More dropdown', () => {
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

    function renderNested(onChange: jest.Mock = jest.fn()): jest.Mock {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true,
        })
        render(
            <Provider>
                <More
                    overlay={
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value=""
                            groupTypes={ADD_COLUMN_GROUP_TYPES}
                            placeholder="Add column left"
                            type="tertiary"
                            fullWidth
                            onChange={onChange}
                        />
                    }
                />
            </Provider>
        )
        return onChange
    }

    /** Open the `More` overlay, then the picker inside it. */
    async function openPickerInsideOverlay(): Promise<void> {
        await userEvent.click(screen.getByLabelText('more'))
        await waitFor(() => expect(screen.getByText('Add column left')).toBeInTheDocument())
        await userEvent.click(screen.getByText('Add column left'))
        await waitFor(() => expect(screen.getByTestId('taxonomic-filter-menu-hogql')).toBeInTheDocument())
    }

    it('opens the rebuilt menu without dismissing the enclosing overlay', async () => {
        renderNested()

        await openPickerInsideOverlay()

        expect(screen.getByTestId('taxonomic-popover-menu-trigger')).toBeInTheDocument()
    })

    it('keeps the enclosing overlay when clicking inside the portaled menu', async () => {
        renderNested()
        await openPickerInsideOverlay()

        // The menu portals out of the parent overlay, so without the fix this
        // click reads as "outside" and dismisses the picker before it can commit.
        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-new'))

        await waitFor(() => expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument())
        expect(screen.getByTestId('taxonomic-popover-menu-trigger')).toBeInTheDocument()
    })

    it('commits a picked property so "Add column" actually adds one', async () => {
        // The OP symptom: with the rebuilt-menu flag on, "Add column left/right"
        // did nothing. Picking a property portals out of the enclosing More
        // overlay, so without the fix that click dismissed the overlay and the
        // selection never reached onChange. Assert the selection commits.
        const onChange = renderNested()
        await openPickerInsideOverlay()

        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-new'))
        await waitFor(() => expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument())
        await userEvent.type(screen.getByTestId('menu-filter-search'), 'purchase_value')

        // The name and value cells both render the property, so target the row.
        const cell = (await screen.findAllByText('purchase_value'))[0]
        const row = cell.closest('[data-slot="taxonomic-filter-menu-row"]')
        await userEvent.click(row as HTMLElement)

        await waitFor(() => expect(onChange).toHaveBeenCalled())
        const [value, groupType] = onChange.mock.calls[onChange.mock.calls.length - 1]
        expect(value).toBe('purchase_value')
        expect(groupType).toBe(TaxonomicFilterGroupType.EventProperties)
    })
})
