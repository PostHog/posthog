import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { TaxonomicFilterHeadless } from '../headless'
import { __clearTaxonomicResourceCache } from '../hooks/useTaxonomicResource'
import { TaxonomicFilterGroupType } from '../types'
import { TaxonomicFilterMenu } from './TaxonomicFilterMenu'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/api', () => {
    const emptyPaginated = (): Promise<{ results: any[]; count: number; next: null }> =>
        Promise.resolve({ results: [], count: 0, next: null })
    return {
        __esModule: true,
        default: {
            get: jest.fn().mockImplementation(emptyPaginated),
            actions: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseSavedQueries: { list: jest.fn().mockImplementation(emptyPaginated) },
            dataWarehouseTables: { list: jest.fn().mockImplementation(emptyPaginated) },
            queryTabState: { list: jest.fn().mockImplementation(emptyPaginated) },
            dashboards: { list: jest.fn().mockImplementation(emptyPaginated) },
            cohorts: { listPaginated: jest.fn().mockImplementation(emptyPaginated) },
        },
    }
})

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>

const GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.HogQLExpression,
]

function renderInputTriggerMenu(): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicFilterHeadless.Root taxonomicGroupTypes={GROUP_TYPES} onChange={jest.fn()}>
                <TaxonomicFilterMenu triggerVariant="input" />
            </TaxonomicFilterHeadless.Root>
        </Provider>
    )
}

describe('TaxonomicFilterMenu input trigger', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        apiGet.mockResolvedValue({ results: [], count: 0, next: null })
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({})
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    it('renders a text input and a filter-icon menu button instead of a single button', () => {
        renderInputTriggerMenu()

        expect(screen.getByTestId('taxonomic-filter-menu-input')).toBeInTheDocument()
        expect(screen.getByRole('textbox')).toBeInTheDocument()
        expect(screen.getByLabelText('Open filter menu')).toBeInTheDocument()
    })

    it('opens the dropdown menu (without a redundant "New filter…" item) when the filter icon is clicked', async () => {
        renderInputTriggerMenu()

        await userEvent.click(screen.getByLabelText('Open filter menu'))

        // The menu opens — its always-present "HogQL expression" entry confirms it.
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-menu-hogql')).toBeInTheDocument()
        })
        // Typing in the box replaces "New filter…", so it must not be offered.
        expect(screen.queryByTestId('taxonomic-filter-menu-new')).not.toBeInTheDocument()
        expect(screen.queryByText('New filter…')).not.toBeInTheDocument()
        // The icon opens the menu, NOT the combobox — guards the `stopPropagation`
        // that keeps the click from bubbling to the input's focus handler.
        expect(screen.queryByTestId('menu-filter-search')).not.toBeInTheDocument()
    })

    it('opens the combobox search panel when the input is focused', async () => {
        renderInputTriggerMenu()

        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-input'))

        await waitFor(() => {
            expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument()
        })
        // The dropdown menu must not also be open — focusing the input is the
        // combobox path, not the menu path.
        expect(screen.queryByTestId('taxonomic-filter-menu-hogql')).not.toBeInTheDocument()
    })

    it('keeps a single search input — the combobox chrome opens around the trigger box, not a second mirrored input', async () => {
        renderInputTriggerMenu()

        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-input'))

        await waitFor(() => {
            expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument()
        })
        // The placeholder trigger input is replaced by the search field, not
        // mirrored alongside it — so there's a single live input, not two.
        expect(screen.queryByTestId('taxonomic-filter-menu-input')).not.toBeInTheDocument()
        // The search field renders in the trigger row beside the filter-icon
        // button (chrome opens around it), not adrift in the popover.
        const iconButton = screen.getByLabelText('Open filter menu')
        const searchInput = screen.getByTestId('menu-filter-search')
        expect(iconButton.closest('.LemonInput')).toContainElement(searchInput)
    })
})
