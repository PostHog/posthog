import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
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

describe('TaxonomicPropertyFilter triggerVariant (rebuild menu)', () => {
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
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true,
        })
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        unmountFeatureFlagLogic?.()
        unmountFeatureFlagLogic = null
        cleanup()
    })

    function renderWith(triggerVariant?: 'button' | 'input'): void {
        render(
            <Provider>
                <PropertyFilters
                    pageKey="input-trigger-test"
                    propertyFilters={[]}
                    onChange={jest.fn()}
                    disablePopover
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    triggerVariant={triggerVariant}
                />
            </Provider>
        )
    }

    it.each([
        { name: 'renders the button trigger by default', triggerVariant: undefined, expectInput: false },
        {
            name: 'renders the button trigger for triggerVariant="button"',
            triggerVariant: 'button',
            expectInput: false,
        },
        {
            name: 'renders the input-box trigger for triggerVariant="input"',
            triggerVariant: 'input',
            expectInput: true,
        },
    ] as const)('$name', async ({ triggerVariant, expectInput }) => {
        renderWith(triggerVariant)

        if (expectInput) {
            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-filter-menu-input')).toBeInTheDocument()
            })
        } else {
            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-popover-menu-trigger')).toBeInTheDocument()
            })
            expect(screen.queryByTestId('taxonomic-filter-menu-input')).not.toBeInTheDocument()
        }
    })
})
