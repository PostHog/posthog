import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { __clearTaxonomicResourceCache } from 'lib/components/TaxonomicFilter/hooks/useTaxonomicResource'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { emptyPaginated } from '~/test/mocks/taxonomicFilterApiMock'

import { TaxonomicPopoverMenu } from './TaxonomicPopoverMenu'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/api', () => require('~/test/mocks/taxonomicFilterApiMock').buildTaxonomicFilterApiMock())

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>

function renderInputTriggerPopoverMenu(): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicPopoverMenu
                groupType={TaxonomicFilterGroupType.EventProperties}
                groupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.HogQLExpression]}
                triggerVariant="input"
                onChange={jest.fn()}
            />
        </Provider>
    )
}

describe('TaxonomicPopoverMenu input trigger (lazy placeholder)', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        apiGet.mockImplementation(emptyPaginated)
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({})
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    it('renders the placeholder input + filter-icon button before arming', () => {
        renderInputTriggerPopoverMenu()

        expect(screen.getByTestId('taxonomic-filter-menu-input')).toBeInTheDocument()
        expect(screen.getByLabelText('Open filter menu')).toBeInTheDocument()
    })

    it('arms to the dropdown menu (not the combobox) when the filter icon is clicked from the resting trigger', async () => {
        renderInputTriggerPopoverMenu()

        await userEvent.click(screen.getByLabelText('Open filter menu'))

        // The icon arms straight to the menu — its "HogQL expression" entry confirms it.
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-menu-hogql')).toBeInTheDocument()
        })
        // It must NOT open the combobox: the icon click must not bubble to the
        // input's focus handler, which would arm the combobox instead.
        expect(screen.queryByTestId('menu-filter-search')).not.toBeInTheDocument()
    })
})
