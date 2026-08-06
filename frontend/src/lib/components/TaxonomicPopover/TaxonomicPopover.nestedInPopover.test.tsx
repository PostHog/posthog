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

    function renderNested(): void {
        render(
            <Provider>
                <More
                    overlay={
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value=""
                            groupTypes={[
                                TaxonomicFilterGroupType.HogQLExpression,
                                TaxonomicFilterGroupType.EventProperties,
                            ]}
                            placeholder="Add column left"
                            type="tertiary"
                            fullWidth
                            onChange={jest.fn()}
                        />
                    }
                />
            </Provider>
        )
    }

    it('opens the rebuilt menu without dismissing the enclosing overlay', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true,
        })
        renderNested()
        await userEvent.click(screen.getByLabelText('more'))
        await waitFor(() => expect(screen.getByText('Add column left')).toBeInTheDocument())

        await userEvent.click(screen.getByText('Add column left'))

        await waitFor(() => expect(screen.getByTestId('taxonomic-filter-menu-hogql')).toBeInTheDocument())
        expect(screen.getByTestId('taxonomic-popover-menu-trigger')).toBeInTheDocument()
    })
})
